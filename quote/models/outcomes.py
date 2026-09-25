"""
BidOutcome — post-award reconciliation, one row per submitted QuoteBid.

Joins a bid to the sales.DibbsAward for the same solicitation + NSN and freezes
the bid's cost basis at submit time, so later edits to supplier pricing, NSN
dimensions or markup defaults never rewrite history (Quote.md Phase 4 §2,
"STATZ Frozen Bid Snapshot").

Table: quote_bid_outcome.
"""
from decimal import Decimal

from django.db import models

from .base import AuditModel


class BidOutcome(AuditModel):
    """Won/lost reconciliation plus the frozen snapshot of how we priced it."""

    OUTCOME_PENDING = 'PENDING'
    OUTCOME_WON = 'WON'
    OUTCOME_LOST = 'LOST'
    OUTCOME_CHOICES = [
        (OUTCOME_PENDING, 'Pending'),
        (OUTCOME_WON, 'Won'),
        (OUTCOME_LOST, 'Lost'),
    ]

    bid = models.OneToOneField(
        'quote.QuoteBid',
        on_delete=models.CASCADE,
        related_name='outcome',
    )
    # Read-only reference into the sales DIBBS tables. Null until the award
    # lands in dibbs_award.
    award = models.ForeignKey(
        'sales.DibbsAward',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_bid_outcomes',
    )

    outcome = models.CharField(
        max_length=10,
        choices=OUTCOME_CHOICES,
        default=OUTCOME_PENDING,
        db_index=True,
    )
    submission_date = models.DateField(db_index=True)

    # ── Our submitted number ──────────────────────────────────────────────
    our_unit_price = models.DecimalField(max_digits=13, decimal_places=5)

    # ── The winning number ────────────────────────────────────────────────
    award_total_price = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
    )
    award_quantity = models.IntegerField(
        null=True, blank=True,
        help_text='Quantity used to derive the unit price. The DIBBS AW file '
                  'carries no quantity, so this comes from the solicitation '
                  'line -- an approximation on multi-line awards.',
    )
    award_unit_price = models.DecimalField(
        max_digits=13, decimal_places=5, null=True, blank=True,
        help_text='DERIVED: award_total_price / award_quantity. Surface as '
                  'derived in the UI, never as a figure DIBBS published.',
    )
    award_unit_price_is_derived = models.BooleanField(default=True)
    winning_cage = models.CharField(max_length=10, blank=True, default='', db_index=True)
    winning_entity_name = models.CharField(max_length=255, blank=True, default='')

    # ── Deltas (stored so the grid sorts/filters without recomputing) ──────
    dollar_delta = models.DecimalField(
        max_digits=13, decimal_places=5, null=True, blank=True,
        help_text='our_unit_price - award_unit_price.',
    )
    pct_spread = models.DecimalField(
        max_digits=9, decimal_places=4, null=True, blank=True,
        help_text='(our - winning) / winning * 100.',
    )
    within_5_pct = models.BooleanField(
        default=False, db_index=True,
        help_text='Lost by more than 0 and at most 5 percent -- the "Within 5%" '
                  'missed-opportunity counter.',
    )

    # ── Frozen bid snapshot ───────────────────────────────────────────────
    snapshot_supplier_name = models.CharField(max_length=255, blank=True, default='')
    snapshot_supplier_unit_cost = models.DecimalField(
        max_digits=13, decimal_places=5, null=True, blank=True,
    )
    snapshot_packhouse_name = models.CharField(max_length=255, blank=True, default='')
    snapshot_packaging_adder_unit = models.DecimalField(
        max_digits=13, decimal_places=5, default=Decimal('0'),
    )
    snapshot_freight_adder_unit = models.DecimalField(
        max_digits=13, decimal_places=5, default=Decimal('0'),
    )
    snapshot_weight_lbs = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
    )
    snapshot_dimensions = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Formatted L x W x H at submit time, e.g. 4" x 2" x 1".',
    )
    snapshot_margin_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )
    snapshot_submitter_name = models.CharField(max_length=150, blank=True, default='')
    source_email = models.ForeignKey(
        'quote.QuoteEmail',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bid_outcomes',
        help_text='The supplier reply the quoted numbers were transcribed from.',
    )

    reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'quote_bid_outcome'
        verbose_name = 'Bid outcome'
        verbose_name_plural = 'Bid outcomes'
        indexes = [
            models.Index(fields=['outcome', 'submission_date'],
                         name='quote_outcome_status_date'),
            models.Index(fields=['within_5_pct', 'submission_date'],
                         name='quote_outcome_tight'),
        ]

    def __str__(self):
        return f'{self.outcome} bid={self.bid_id}'
