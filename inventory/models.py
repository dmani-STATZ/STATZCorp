from django.conf import settings
from django.db import models


class InventoryItem(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=50,  blank=True, null=True)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=250, blank=True, null=True)  # Field name made lowercase.
    partnumber = models.CharField(db_column='PartNumber', max_length=50, blank=True, null=True)  # Field name made lowercase.
    manufacturer = models.CharField(db_column='Manufacturer', max_length=50, blank=True, null=True)  # Field name made lowercase.
    itemlocation = models.CharField(db_column='ItemLocation', max_length=50, blank=True, null=True)  # Field name made lowercase.
    quantity = models.IntegerField(db_column='Quantity', blank=True, null=True)  # Field name made lowercase.
    quantity_remaining = models.IntegerField(null=True, blank=True)
    purchaseprice = models.FloatField(db_column='PurchasePrice', blank=True, null=True)  # Field name made lowercase.
    totalcost = models.FloatField(db_column='TotalCost', blank=True, null=True, editable=False)  # Field name made lowercase.
    is_public = models.BooleanField(default=False)
    last_modified = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        db_table = 'STATZ_WAREHOUSE_INVENTORY_TBL'

    def __str__(self):
        return self.nsn or self.description or f'Inventory item {self.pk}'

    @property
    def on_hand(self):
        if self.quantity_remaining is not None:
            return self.quantity_remaining
        return self.quantity or 0

    @property
    def on_hand_value(self):
        if self.purchaseprice is None:
            return None
        return self.on_hand * self.purchaseprice

    def save(self, *args, **kwargs):
        if self.quantity is not None and self.purchaseprice is not None:
            self.totalcost = self.purchaseprice * self.quantity
        else:
            self.totalcost = None
        super().save(*args, **kwargs)


class InventorySyncRun(models.Model):
    STATUS_PREVIEW = 'preview'
    STATUS_APPLIED = 'applied'
    STATUS_DISCARDED = 'discarded'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = (
        (STATUS_PREVIEW, 'Preview'),
        (STATUS_APPLIED, 'Applied'),
        (STATUS_DISCARDED, 'Discarded'),
        (STATUS_FAILED, 'Failed'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    original_filename = models.CharField(max_length=255, blank=True, default='')
    file_bytes = models.BinaryField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PREVIEW)
    plan = models.JSONField(default=dict)
    errors = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Inventory sync {self.pk} ({self.status})'
