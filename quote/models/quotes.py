"""
QuoteSupplierQuote — a supplier's price for one solicitation line, with the full
landed-cost buildup.

This is Quote.md's `Supplier_Quotes` table: every adder, markup and derived
field needed to reproduce the government unit price.

Table: quote_supplier_quote.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from .base import AuditModel


class QuoteSupplierQuote(AuditModel):
    """One supplier's quote for one line, priced through to a government unit price."""

    MARKUP_PERCENTAGE = 'PCT'
    MARKUP_FIXED_PRICE = 'FIXED'
    MARKUP_TYPE_CHOICES = [
        (MARKUP_PERCENTAGE, 'Percentage'),
        (MARKUP_FIXED_PRICE, 'Fixed price'),
    ]

    PACKAGING_SUPPLIER_INCLUDED = 'INCLUDED'
    PACKAGING_IN_HOUSE = 'IN_HOUSE'
    PACKAGING_THIRD_PARTY = 'THIRD_PARTY'
    PACKAGING_SOURCE_CHOICES = [
        (PACKAGING_SUPPLIER_INCLUDED, 'Included by part supplier'),
        (PACKAGING_IN_HOUSE, 'In-house'),
        (PACKAGING_THIRD_PARTY, 'Third-party packhouse'),
    ]

    rfq = models.ForeignKey(
        'quote.QuoteRFQ',
        on_delete=models.CASCADE,
        related_name='quotes',
        null=True,
        blank=True,
        help_text='Null for a quote logged against a line with no outbound RFQ.',
    )
    # Read-only references into the dibbs tables.
    line = models.ForeignKey(
        'dibbs.SolicitationLine',
        on_delete=models.CASCADE,
        related_name='quote_supplier_quotes',
    )
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='quote_supplier_quotes',
    )
    nsn = models.CharField(
        max_length=46,
        db_index=True,
        help_text='Denormalized from the line at save time for fast NSN rollups.',
    )

    # ── Supplier's own numbers ────────────────────────────────────────────
    supplier_unit_cost = models.DecimalField(max_digits=13, decimal_places=5)
    lead_time_days = models.IntegerField(
        help_text='Quoted delivery days ARO. Whole numbers only (BQ col 51).',
    )
    min_order_qty = models.IntegerField(null=True, blank=True)
    quantity_available = models.IntegerField(null=True, blank=True)
    offered_part_number = models.CharField(max_length=40, blank=True, default='')
    offered_cage = models.CharField(max_length=5, blank=True, default='')
    payment_terms = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text='Quote-specific terms. Compare against the supplier default to '
                  'show the diff indicator.',
    )

    # ── Packaging adder ───────────────────────────────────────────────────
    packaging_source = models.CharField(
        max_length=12,
        choices=PACKAGING_SOURCE_CHOICES,
        default=PACKAGING_SUPPLIER_INCLUDED,
    )
    packaging_vendor = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_packaging_jobs',
        help_text='The chosen packhouse. Selected from suppliers.Supplier '
                  '(is_packhouse / supplier_type=Packhouse as a sort hint).',
    )
    packaging_total_cost = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
        help_text='Total pack cost as quoted by the packhouse, if quoted as a total.',
    )
    packaging_adder_unit = models.DecimalField(
        max_digits=13, decimal_places=5, default=Decimal('0'),
        help_text='Per-unit packaging cost. total / quantity when quoted as a total.',
    )

    # ── Freight adder ─────────────────────────────────────────────────────
    freight_total_cost = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
        help_text='Total freight as quoted, if quoted as a total.',
    )
    freight_adder_unit = models.DecimalField(
        max_digits=13, decimal_places=5, default=Decimal('0'),
        help_text='Per-unit freight cost. total / quantity when quoted as a total.',
    )

    # ── Markup and the resulting government price ─────────────────────────
    markup_type = models.CharField(
        max_length=5,
        choices=MARKUP_TYPE_CHOICES,
        default=MARKUP_PERCENTAGE,
    )
    markup_value = models.DecimalField(
        max_digits=13, decimal_places=5, default=Decimal('0'),
        help_text='Percent when markup_type=PCT, else the target unit sell price.',
    )
    final_government_unit_price = models.DecimalField(
        max_digits=13, decimal_places=5, null=True, blank=True,
        help_text='What goes into BQ col 50. Computed by '
                  'quote.services.cost_buildup, stored so the bid is reproducible.',
    )

    is_selected_for_bid = models.BooleanField(default=False, db_index=True)
    selected_automatically = models.BooleanField(
        default=False,
        help_text='True when the system auto-picked this as lowest landed cost, '
                  'so the UI can show the "Auto: Lowest" badge.',
    )

    source_email = models.ForeignKey(
        'quote.QuoteEmail',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplier_quotes',
        help_text='The supplier reply these numbers were transcribed from, so '
                  'the quote screen can link straight back to it.',
    )

    notes = models.TextField(blank=True, default='')
    quote_date = models.DateTimeField(auto_now_add=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_supplier_quotes_entered',
    )

    class Meta:
        db_table = 'quote_supplier_quote'
        verbose_name = 'Quote supplier quote'
        verbose_name_plural = 'Quote supplier quotes'
        indexes = [
            models.Index(fields=['line', 'is_selected_for_bid'],
                         name='quote_sq_line_selected'),
        ]

    def __str__(self):
        return f'{self.supplier_id} @ {self.supplier_unit_cost} (line {self.line_id})'

    @property
    def landed_unit_cost(self) -> Decimal:
        """Supplier cost plus both adders. Decimal throughout -- never float."""
        return (
            (self.supplier_unit_cost or Decimal('0'))
            + (self.packaging_adder_unit or Decimal('0'))
            + (self.freight_adder_unit or Decimal('0'))
        )
