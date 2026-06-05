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
        return (self.data or {}).get('parser', {}).get('source') == 'dibbs'

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
