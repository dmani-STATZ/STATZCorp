"""
ApprovedSource — from AS file. Section 3.2.
Table: tbl_ApprovedSource.
"""
from django.db import models

from .solicitations import ImportBatch


class ApprovedSource(models.Model):
    """NSN → approved CAGE → part number from AS file."""
    nsn = models.CharField(max_length=46, db_index=True)
    approved_cage = models.CharField(max_length=5, db_index=True)
    part_number = models.CharField(max_length=50, null=True, blank=True)
    company_name = models.CharField(max_length=100, null=True, blank=True)
    import_batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_sources',
    )

    class Meta:
        db_table = 'tbl_ApprovedSource'
        verbose_name = 'Approved source'
        verbose_name_plural = 'Approved sources'
