"""
QuoteBid — the staged DIBBS submission for one solicitation line.

The staged DIBBS bid for one line. Carries every column the BQ
overlay writes, plus clin_group so a combined-CLIN entry can drive sibling
lines from one form (Quote.md Phase 2 "Default Mode (Combined / Linked)").

Table: quote_bid.
"""
from django.conf import settings
from django.db import models

from .base import AuditModel


class QuoteBid(AuditModel):
    """One bid per solicitation line, staged for BQ export."""

    STATUS_DRAFT = 'DRAFT'
    STATUS_READY = 'READY'
    STATUS_SUBMITTED = 'SUBMITTED'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_READY, 'Ready to export'),
        (STATUS_SUBMITTED, 'Submitted'),
    ]

    # Bid type codes -- BQ col 24.
    BID_WITHOUT_EXCEPTION = 'BI'
    BID_WITH_EXCEPTION = 'BW'
    BID_ALTERNATE = 'AB'
    BID_NO_QUOTE = 'DQ'
    BID_TYPE_CHOICES = [
        (BID_WITHOUT_EXCEPTION, 'Without exception'),
        (BID_WITH_EXCEPTION, 'With exception'),
        (BID_ALTERNATE, 'Alternate bid'),
        (BID_NO_QUOTE, 'No bid'),
    ]

    # Read-only reference into the dibbs tables. The solicitation is reached
    # through the line -- no separate FK, so the two can never disagree.
    line = models.OneToOneField(
        'dibbs.SolicitationLine',
        on_delete=models.CASCADE,
        related_name='quote_bid',
    )
    selected_quote = models.ForeignKey(
        'quote.QuoteSupplierQuote',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bids',
    )

    clin_group = models.CharField(
        max_length=36,
        blank=True,
        default='',
        help_text='Shared key across sibling lines priced together in Combined '
                  'mode. Blank means this line was priced independently (Split).',
    )

    # ── BQ header columns ─────────────────────────────────────────────────
    quoter_cage = models.CharField(max_length=5)                 # col 6
    quote_for_cage = models.CharField(max_length=5)              # col 7
    bid_type_code = models.CharField(                            # col 24
        max_length=2, choices=BID_TYPE_CHOICES, default=BID_WITHOUT_EXCEPTION,
    )
    payment_terms = models.CharField(max_length=2, blank=True, default='')   # col 25
    vendor_quote_number = models.CharField(max_length=15, blank=True, default='')  # col 26
    days_quote_valid = models.PositiveSmallIntegerField(default=90)          # col 27
    meets_packaging_requirement = models.CharField(max_length=1, default='Y')  # col 28
    fob_point = models.CharField(max_length=1, default='D')       # col 32
    inspection_point = models.CharField(max_length=1, default='D')  # col 36

    # ── BQ line columns ───────────────────────────────────────────────────
    unit_price = models.DecimalField(max_digits=13, decimal_places=5)  # col 50
    delivery_days = models.IntegerField()                              # col 51

    # ── BQ product columns ────────────────────────────────────────────────
    first_article_waiver = models.CharField(max_length=1, blank=True, default='')  # col 64
    hazardous_material = models.CharField(max_length=1, default='N')   # col 65
    material_requirements = models.CharField(max_length=1, default='0')  # col 67
    manufacturer_dealer = models.CharField(max_length=2)               # col 102
    mfg_source_cage = models.CharField(max_length=5, blank=True, default='')  # col 103
    part_number_offered_code = models.CharField(max_length=1, blank=True, default='')  # col 106
    part_number_offered_cage = models.CharField(max_length=5, blank=True, default='')  # col 107
    part_number_offered = models.CharField(max_length=40, blank=True, default='')      # col 108
    higher_level_quality_code = models.CharField(max_length=1, blank=True, default='')  # col 118
    bid_remarks = models.CharField(max_length=255, blank=True, default='')  # col 121

    # ── Margin provenance ─────────────────────────────────────────────────
    margin_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Effective margin actually applied, back-calculated when the '
                  'rep entered a target sell price instead of a percentage.',
    )

    bid_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_bids_submitted',
    )
    exported_bq_file = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'quote_bid'
        verbose_name = 'Quote bid'
        verbose_name_plural = 'Quote bids'
        indexes = [
            models.Index(fields=['bid_status', 'submitted_at'],
                         name='quote_bid_status_sub'),
            models.Index(fields=['clin_group'], name='quote_bid_clin_group'),
        ]

    def __str__(self):
        return f'Bid line={self.line_id} @ {self.unit_price} ({self.bid_status})'

    @property
    def is_auto_award_solicitation(self) -> bool:
        """
        DIBBS auto-award eligibility is flagged by character 9 of the
        solicitation number being T or U. On those, BQ col 121 (Quote Remarks)
        must stay empty or the solicitation loses auto-award status.
        """
        sol_number = (self.line.solicitation.solicitation_number or '')
        return len(sol_number) >= 9 and sol_number[8].upper() in ('T', 'U')
