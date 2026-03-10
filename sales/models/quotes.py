"""
SupplierQuote — pricing received from supplier. Section 3.4.
Table: dibbs_supplier_quote.
"""
from django.conf import settings
from django.db import models


class SupplierQuote(models.Model):
    """Pricing received from a supplier for a line."""
    rfq = models.ForeignKey(
        'SupplierRFQ',
        on_delete=models.CASCADE,
        related_name='quotes',
    )
    line = models.ForeignKey(
        'SolicitationLine',
        on_delete=models.CASCADE,
        related_name='supplier_quotes',
    )
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='dibbs_quotes',
    )
    nsn = models.CharField(max_length=46, db_index=True)
    unit_price = models.DecimalField(max_digits=13, decimal_places=5)
    lead_time_days = models.IntegerField()
    quantity_available = models.IntegerField(null=True, blank=True)
    part_number_offered = models.CharField(max_length=100, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    quote_date = models.DateTimeField(auto_now_add=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_quotes_entered',
    )
    is_selected_for_bid = models.BooleanField(default=False)

    class Meta:
        db_table = 'dibbs_supplier_quote'
        verbose_name = 'Supplier quote'
        verbose_name_plural = 'Supplier quotes'
