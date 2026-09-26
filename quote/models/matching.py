"""
Supplier capability tables and solicitation-to-supplier matches.

QuoteSupplierNSN / QuoteSupplierFSC say "this supplier can make this NSN / this
FSC". QuoteSolicitationMatch records which suppliers a solicitation was linked
to and why. Matching is additive (Quote.md Phase 1): one row per
(solicitation, supplier, source), so a supplier hit by NSN and FSC and manual
assignment carries all three lineage badges.

Tables: quote_supplier_nsn, quote_supplier_fsc, quote_solicitation_match.
"""
from django.conf import settings
from django.db import models


class QuoteSupplierNSN(models.Model):
    """A supplier's capability for one NSN (13-digit, no hyphens)."""

    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='quote_nsn_capabilities',
    )
    nsn = models.CharField(
        max_length=13,
        db_index=True,
        help_text='Normalized 13-digit NSN, no hyphens.',
    )
    notes = models.TextField(blank=True, default='')
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quote_supplier_nsn'
        unique_together = [('supplier', 'nsn')]
        verbose_name = 'Supplier NSN capability'
        verbose_name_plural = 'Supplier NSN capabilities'

    def __str__(self):
        return f'{self.supplier_id} → NSN {self.nsn}'


class QuoteSupplierFSC(models.Model):
    """A supplier's capability for a whole Federal Supply Class."""

    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='quote_fsc_capabilities',
    )
    fsc = models.CharField(max_length=4, db_index=True)
    notes = models.TextField(blank=True, default='')
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quote_supplier_fsc'
        unique_together = [('supplier', 'fsc')]
        verbose_name = 'Supplier FSC capability'
        verbose_name_plural = 'Supplier FSC capabilities'

    def __str__(self):
        return f'{self.supplier_id} → FSC {self.fsc}'


class QuoteSolicitationMatch(models.Model):
    """One supplier linked to one solicitation, with the reason it was linked."""

    SOURCE_NSN = 'NSN'
    SOURCE_FSC = 'FSC'
    SOURCE_MANUAL = 'MANUAL'
    SOURCE_CHOICES = [
        (SOURCE_NSN, 'NSN'),
        (SOURCE_FSC, 'FSC'),
        (SOURCE_MANUAL, 'Manual'),
    ]

    # Read-only reference into the dibbs tables.
    solicitation = models.ForeignKey(
        'dibbs.Solicitation',
        on_delete=models.CASCADE,
        related_name='quote_matches',
    )
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='quote_solicitation_matches',
    )
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)

    #: Matches are derived (re-created by re-running matching), so dibbs'
    #: import-batch delete may cascade through them.
    dibbs_disposable = True
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text='Null for engine-created NSN / FSC matches.',
    )
    matched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quote_solicitation_match'
        unique_together = [('solicitation', 'supplier', 'source')]
        verbose_name = 'Solicitation supplier match'
        verbose_name_plural = 'Solicitation supplier matches'

    def __str__(self):
        return f'{self.solicitation_id} ↔ {self.supplier_id} [{self.source}]'
