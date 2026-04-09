"""
SupplierNSN, SupplierFSC — DIBBS supplier capability (Section 3.3).
Tables: dibbs_supplier_nsn, dibbs_supplier_fsc.
FK to suppliers.Supplier (contracts_supplier).
"""

from django.conf import settings
from django.db import models


class SupplierNSN(models.Model):
    """Explicit NSN-level supplier capability (manual rows; scores from SQL view)."""

    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.CASCADE,
        related_name="nsn_capabilities",
    )
    nsn = models.CharField(max_length=46, db_index=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nsn_capabilities_added",
    )

    class Meta:
        db_table = "dibbs_supplier_nsn"
        unique_together = ("supplier", "nsn")
        verbose_name = "Supplier NSN"
        verbose_name_plural = "Supplier NSNs"


class SupplierNSNScored(models.Model):
    """
    Unmanaged model — reads from dibbs_supplier_nsn_scored SQL Server view.
    Created manually in SSMS. Never modified by Django migrations.
    Do not add to migrations.
    """

    id = models.BigIntegerField(primary_key=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.DO_NOTHING,
        related_name="nsn_scored",
    )
    nsn = models.CharField(max_length=46)
    match_score = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        managed = False
        db_table = "dibbs_supplier_nsn_scored"


class SolicitationMatchCount(models.Model):
    """
    Unmanaged model — reads from dibbs_solicitation_match_counts SQL Server view.
    Created manually in SSMS. Never modified by Django migrations.
    Provides live T1+T2+T3 additive match count per solicitation.
    """

    solicitation = models.OneToOneField(
        "Solicitation",
        on_delete=models.DO_NOTHING,
        primary_key=True,
        related_name="+",
    )
    match_count = models.IntegerField()

    class Meta:
        managed = False
        db_table = "dibbs_solicitation_match_counts"


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
