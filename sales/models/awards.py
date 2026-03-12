from django.db import models


class DibbsAward(models.Model):
    solicitation  = models.ForeignKey(
        'Solicitation', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='awards',
    )
    sol_number    = models.CharField(max_length=50, db_index=True)
    notice_id     = models.CharField(max_length=100, unique=True)
    award_date    = models.DateField()
    award_amount  = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    awardee_name  = models.CharField(max_length=200, blank=True)
    awardee_cage  = models.CharField(max_length=10, blank=True, db_index=True)
    we_bid        = models.BooleanField(default=False)
    we_won        = models.BooleanField(default=False)
    sam_data      = models.JSONField(default=dict)
    synced_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dibbs_award'
