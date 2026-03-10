"""
GovernmentBid — the bid we submit to DIBBS. Section 3.4.
Table: dibbs_government_bid.
"""
from django.db import models


class GovernmentBid(models.Model):
    """One bid per solicitation line submitted to DIBBS."""
    BID_STATUS = [
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
    ]
    solicitation = models.ForeignKey(
        'Solicitation',
        on_delete=models.CASCADE,
        related_name='bids',
    )
    line = models.OneToOneField(
        'SolicitationLine',
        on_delete=models.CASCADE,
        related_name='bid',
    )
    selected_quote = models.ForeignKey(
        'SupplierQuote',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bid',
    )
    quoter_cage = models.CharField(max_length=5)
    quote_for_cage = models.CharField(max_length=5)
    bid_type_code = models.CharField(max_length=2)  # BI/BW/AB/DQ
    unit_price = models.DecimalField(max_digits=13, decimal_places=5)
    delivery_days = models.IntegerField()
    manufacturer_dealer = models.CharField(max_length=2)  # MM/DD/QM/QD
    mfg_source_cage = models.CharField(max_length=5, null=True, blank=True)
    fob_point = models.CharField(max_length=1, default='D')
    bid_status = models.CharField(max_length=20, choices=BID_STATUS, default='DRAFT')
    submitted_at = models.DateTimeField(null=True, blank=True)
    exported_bq_file = models.CharField(max_length=255, null=True, blank=True)
    bid_remarks = models.CharField(max_length=255, null=True, blank=True)
    margin_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = 'dibbs_government_bid'
        verbose_name = 'Government bid'
        verbose_name_plural = 'Government bids'
