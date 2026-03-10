"""
Solicitation, SolicitationLine, ImportBatch — Section 3.1.
Tables: dibbs_solicitation, dibbs_solicitation_line, tbl_ImportBatch.
"""
from django.db import models


class ImportBatch(models.Model):
    """Tracks each daily DIBBS file import (IN, BQ, AS)."""
    import_date = models.DateField()
    in_file_name = models.CharField(max_length=50, null=True, blank=True)
    bq_file_name = models.CharField(max_length=50, null=True, blank=True)
    as_file_name = models.CharField(max_length=50, null=True, blank=True)
    imported_at = models.DateTimeField()
    solicitation_count = models.IntegerField(default=0)
    imported_by = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = 'tbl_ImportBatch'
        verbose_name = 'Import batch'
        verbose_name_plural = 'Import batches'


class Solicitation(models.Model):
    """One row per solicitation (from IN/BQ)."""
    STATUS_CHOICES = [
        ('New', 'New'),
        ('Reviewing', 'Reviewing'),
        ('RFQ Sent', 'RFQ Sent'),
        ('Bid Submitted', 'Bid Submitted'),
        ('No Bid', 'No Bid'),
        ('Won', 'Won'),
        ('Lost', 'Lost'),
    ]
    solicitation_number = models.CharField(max_length=13, unique=True, db_index=True)
    solicitation_type = models.CharField(max_length=1, null=True, blank=True)  # F/I/P
    small_business_set_aside = models.CharField(max_length=1, null=True, blank=True)  # N/Y/H/R/L/A/E
    return_by_date = models.DateField(null=True, blank=True)
    pdf_file_name = models.CharField(max_length=50, null=True, blank=True)
    buyer_code = models.CharField(max_length=5, null=True, blank=True)
    import_date = models.DateField(null=True, blank=True)
    import_batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitations',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='New')

    class Meta:
        db_table = 'dibbs_solicitation'
        verbose_name = 'Solicitation'
        verbose_name_plural = 'Solicitations'


class SolicitationLine(models.Model):
    """One row per NSN/line within a solicitation."""
    solicitation = models.ForeignKey(
        Solicitation,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    line_number = models.CharField(max_length=4, null=True, blank=True)
    purchase_request_number = models.CharField(max_length=13, null=True, blank=True)
    nsn = models.CharField(max_length=46, db_index=True)
    fsc = models.CharField(max_length=4, null=True, blank=True)
    niin = models.CharField(max_length=9, null=True, blank=True)
    unit_of_issue = models.CharField(max_length=2, null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    delivery_days = models.IntegerField(null=True, blank=True)
    nomenclature = models.CharField(max_length=21, null=True, blank=True)
    amsc = models.CharField(max_length=1, null=True, blank=True)
    item_type_indicator = models.CharField(max_length=1, null=True, blank=True)
    item_description_indicator = models.CharField(max_length=1, null=True, blank=True)
    trade_agreements_indicator = models.CharField(max_length=1, null=True, blank=True)
    buy_american_indicator = models.CharField(max_length=1, null=True, blank=True)
    higher_level_quality_indicator = models.CharField(max_length=1, null=True, blank=True)

    class Meta:
        db_table = 'dibbs_solicitation_line'
        verbose_name = 'Solicitation line'
        verbose_name_plural = 'Solicitation lines'
