"""Intake app models.

A single `DraftContract` model holds every contract type during the intake
phase. Type-specific fields and child records live in the `data` JSONField
and are validated on every save by a per-`contract_type` Pydantic schema
(see intake/schemas.py).

Design constraint: drafts are NOT contracts. They exist to be finalized into
the canonical `contracts` app tables, after which the draft is deleted.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from contracts.models import Contract

from .locks import LOCK_DURATION, is_expired
from .schemas import DraftDataValidationError, validate_data


class DraftContract(models.Model):
    """In-flight contract draft awaiting analyst review and finalization."""

    class Type(models.TextChoices):
        AWD = 'AWD', 'Award'
        PO = 'PO', 'Purchase Order'
        DO = 'DO', 'Delivery Order'
        IDIQ = 'IDIQ', 'IDIQ'
        MOD = 'MOD', 'Modification'
        AMD = 'AMD', 'Amendment'
        INTERNAL = 'INTERNAL', 'Internal'

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        IN_PROGRESS = 'in_progress', 'In Progress'
        READY_FOR_REVIEW = 'ready_for_review', 'Ready for Review'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    class PdfParseStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        NO_PDF = 'no_pdf', 'No PDF'
        PARSEABLE = 'parseable', 'Parseable'
        PARTIAL = 'partial', 'Parsed with Warnings'
        SUCCESS = 'success', 'Success'

    contract_number = models.CharField(
        max_length=25,
        unique=True,
        help_text='Unique identity; enforces dedup against re-injection.',
    )
    contract_type = models.CharField(max_length=10, choices=Type.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.QUEUED
    )

    # Soft edit lock (30-minute expiry — see intake/locks.py)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='intake_locked_drafts',
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    pdf_parse_status = models.CharField(
        max_length=20,
        choices=PdfParseStatus.choices,
        default=PdfParseStatus.PENDING,
    )

    data = models.JSONField(
        default=dict,
        help_text='Type-specific fields, child records, parser provenance. '
                  'Validated per contract_type by intake.schemas.validate_data.',
    )

    # Set briefly at finalization, then the draft is deleted. Nullable because
    # 99% of a draft's lifetime is pre-finalization.
    final_contract = models.ForeignKey(
        Contract,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='intake_source_drafts',
    )

    company = models.ForeignKey(
        'contracts.Company',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='draft_contracts',
        help_text='Company this draft belongs to. Set at ingestion time.',
    )

    sharepoint_folder_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('exists', 'Exists'),
            ('not_found', 'Not Found'),
            ('created', 'Created'),
            ('error', 'Error'),
        ],
        default='pending',
        help_text=(
            'Whether the SharePoint folder for this contract has been confirmed '
            'or created.'
        ),
    )

    created_at = models.DateTimeField(default=timezone.now)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Draft Contract'
        verbose_name_plural = 'Draft Contracts'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['contract_type']),
            models.Index(fields=['locked_by']),
            models.Index(fields=['created_at']),
            models.Index(fields=['company'], name='intake_draf_company_idx'),
        ]

    def __str__(self):
        return f'DraftContract {self.contract_number} ({self.contract_type})'

    def save(self, *args, **kwargs):
        # Always re-validate JSON on save. The per-type Pydantic schema is the
        # single gate — without it, parsers and templates would silently
        # disagree on key names and old records would rot.
        if self.contract_type:
            try:
                self.data = validate_data(self.contract_type, self.data or {})
            except DraftDataValidationError:
                raise
        super().save(*args, **kwargs)

    # ---- lock convenience -------------------------------------------------

    @property
    def is_locked(self) -> bool:
        return self.locked_by_id is not None and not is_expired(self.locked_at)

    @property
    def lock_expires_at(self):
        if self.locked_at is None:
            return None
        return self.locked_at + LOCK_DURATION

    @property
    def is_dibbs_draft(self) -> bool:
        """True if this draft originated from the DIBBS awards scraper."""
        data = self.data or {}
        parser = data.get('parser')
        if not isinstance(parser, dict):
            return False
        return parser.get('source') == 'dibbs'

    @property
    def lock_active(self) -> bool:
        """True if the edit lock is currently active."""
        return self.is_locked

    @property
    def lock_expired(self) -> bool:
        """True if the edit lock has expired."""
        return self.locked_by_id is not None and is_expired(self.locked_at)

    def acquire_lock(self, user) -> None:
        """Acquire lock for this user."""
        from .locks import acquire
        acquire(self, user)

    def release_lock(self, user) -> None:
        """Release lock for this user."""
        from .locks import release
        release(self, user)


class AwardLedger(models.Model):
    """Durable, one-row-per-contract-identity ledger of the DIBBS award lifecycle.

    This is the ONLY persistent record of the award → draft → live-contract
    journey. `DraftContract.final_contract` is deleted together with the draft
    on finalization, so nothing else survives to answer questions like
    "did we win this, was a draft created, was it worked, did it become a
    live contract, and when did each of those happen?".

    Latching invariant: the `*_at` lifecycle timestamps are WRITE-ONCE. Once
    set they are never overwritten or cleared. `lifecycle_state` is recomputed
    each sweep but may only advance (never regress). Mirror columns and the
    boolean/link fields are refreshed on every sweep.

    Scope: all contracts entering the intake queue (regardless of source)
    are recorded here.
    """

    class Lifecycle(models.TextChoices):
        NOT_WE_WON = 'not_we_won', 'Not We-Won'
        MOD_ONLY = 'mod_only', 'Mod Only'
        AWAITING_DRAFT = 'awaiting_draft', 'Awaiting Draft'
        IN_DRAFT = 'in_draft', 'In Draft'
        DRAFT_WORKED = 'draft_worked', 'Draft Worked'
        LIVE_CONTRACT = 'live_contract', 'Live Contract'

    # Advance-only ranking of lifecycle states. Higher wins; never regress.
    LIFECYCLE_RANK = {
        Lifecycle.NOT_WE_WON: 0,
        Lifecycle.MOD_ONLY: 1,
        Lifecycle.AWAITING_DRAFT: 2,
        Lifecycle.IN_DRAFT: 3,
        Lifecycle.DRAFT_WORKED: 4,
        Lifecycle.LIVE_CONTRACT: 5,
    }

    class IngestionSource(models.TextChoices):
        DIBBS_SCRAPE = 'dibbs_scrape', 'DIBBS Scrape'
        DIBBS_POLL = 'dibbs_poll', 'DIBBS Poll'
        PDF_UPLOAD = 'pdf_upload', 'PDF Upload'
        MANUAL = 'manual', 'Manual Entry'
        LEGACY = 'legacy', 'Legacy (pre-tracking)'

    # -- Identity (upsert key) ------------------------------------------------
    contract_number = models.CharField(
        max_length=25,
        unique=True,
        help_text='Canonical (dashed) contract number — matches '
                  'DraftContract.contract_number / Contract.contract_number.',
    )

    # -- DIBBS mirror (types copied from sales.DibbsAward) --------------------
    award_basic_number = models.CharField(max_length=50, blank=True, default='')
    delivery_order_number = models.CharField(max_length=50, blank=True, default='')
    delivery_order_counter = models.CharField(max_length=20, blank=True, default='')
    awardee_cage = models.CharField(max_length=10, blank=True, default='', db_index=True)
    nsn = models.CharField(max_length=46, blank=True, default='')
    nomenclature = models.CharField(max_length=100, blank=True, default='')
    purchase_request = models.CharField(max_length=20, blank=True, default='')
    solicitation = models.CharField(max_length=50, blank=True, default='')

    total_contract_price = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    award_date = models.DateField(null=True, blank=True)
    posted_date = models.DateField(null=True, blank=True)
    aw_file_date = models.DateField(null=True, blank=True)
    last_mod_posting_date = models.DateField(null=True, blank=True)
    mod_count = models.PositiveIntegerField(default=0)

    # -- Classification / links ----------------------------------------------
    is_we_won = models.BooleanField(default=False)
    has_award = models.BooleanField(default=False)
    dibbs_award = models.ForeignKey(
        'sales.DibbsAward',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entries',
    )
    contract = models.ForeignKey(
        'contracts.Contract',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='award_ledger_entries',
    )

    # -- Latched lifecycle timestamps (write-once — never overwrite/clear) ----
    first_seen_at = models.DateTimeField(default=timezone.now)
    draft_created_at = models.DateTimeField(null=True, blank=True)
    draft_worked_at = models.DateTimeField(null=True, blank=True)
    mod_record_created_at = models.DateTimeField(null=True, blank=True)
    live_contract_at = models.DateTimeField(null=True, blank=True)

    # -- User & Ingestion Provenance (latching write-once logic applies) ------
    ingestion_source = models.CharField(
        max_length=20,
        choices=IngestionSource.choices,
        blank=True,
        default='',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_created_contracts',
    )
    draft_worked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_worked_contracts',
    )
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_finalized_contracts',
    )

    # -- Derived / display (recomputed each sweep; advance-only) --------------
    lifecycle_state = models.CharField(
        max_length=20,
        choices=Lifecycle.choices,
        default='',
        db_index=True,
    )

    # -- Bookkeeping ----------------------------------------------------------
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'intake_award_ledger'
        ordering = ['-first_seen_at']
        verbose_name = 'Award Ledger Entry'
        verbose_name_plural = 'Award Ledger Entries'
        indexes = [
            models.Index(fields=['is_we_won'], name='award_ledger_we_won_idx'),
            models.Index(fields=['lifecycle_state'], name='award_ledger_state_idx'),
            models.Index(fields=['awardee_cage'], name='award_ledger_cage_idx'),
            models.Index(fields=['first_seen_at'], name='award_ledger_seen_idx'),
            models.Index(fields=['live_contract_at'], name='award_ledger_live_idx'),
        ]

    def __str__(self):
        return f'AwardLedger {self.contract_number} ({self.lifecycle_state or "new"})'
