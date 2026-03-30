"""
SupplierMatch — results of matching engine. Section 4.1.
Table: dibbs_supplier_match.
"""

from django.db import models


class SupplierMatch(models.Model):
    """One row per supplier-line pairing found by the matching engine."""

    MATCH_METHOD = [
        ("DIRECT_NSN", "Direct NSN"),
        ("APPROVED_SOURCE", "Approved Source"),
        ("FSC", "FSC Category"),
        ("MANUAL", "Manual / Ad-hoc"),
    ]
    line = models.ForeignKey(
        "SolicitationLine",
        on_delete=models.CASCADE,
        related_name="supplier_matches",
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.CASCADE,
        related_name="dibbs_matches",
    )
    match_tier = models.IntegerField()
    match_method = models.CharField(max_length=20, choices=MATCH_METHOD)
    match_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    is_excluded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dibbs_supplier_match"
        unique_together = ("line", "supplier")
        verbose_name = "Supplier match"
        verbose_name_plural = "Supplier matches"
