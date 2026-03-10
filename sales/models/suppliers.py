"""
SupplierNSN, SupplierFSC — DIBBS supplier capability (Section 3.3).
Tables: dibbs_supplier_nsn, dibbs_supplier_fsc.
FK to suppliers.Supplier (contracts_supplier).
"""

from django.db import models


class SupplierNSN(models.Model):
    """Explicit NSN-level supplier capability."""

    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.CASCADE,
        related_name="nsn_capabilities",
    )
    nsn = models.CharField(max_length=46, db_index=True)
    part_number = models.CharField(max_length=100, null=True, blank=True)
    is_preferred = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, null=True, blank=True)
    match_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    source = models.CharField(max_length=20, default="manual")
    last_synced = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "dibbs_supplier_nsn"
        unique_together = ("supplier", "nsn")
        verbose_name = "Supplier NSN"
        verbose_name_plural = "Supplier NSNs"


class SupplierFSC(models.Model):
    """FSC/category-level supplier capability."""

    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.CASCADE,
        related_name="fsc_capabilities",
    )
    fsc_code = models.CharField(max_length=4, db_index=True)
    notes = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "dibbs_supplier_fsc"
        unique_together = ("supplier", "fsc_code")
        verbose_name = "Supplier FSC"
        verbose_name_plural = "Supplier FSCs"
