from django.db import models


class InventoryItem(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=50,  blank=True, null=True)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=250, blank=True, null=True)  # Field name made lowercase.
    partnumber = models.CharField(db_column='PartNumber', max_length=50, blank=True, null=True)  # Field name made lowercase.
    manufacturer = models.CharField(db_column='Manufacturer', max_length=50, blank=True, null=True)  # Field name made lowercase.
    itemlocation = models.CharField(db_column='ItemLocation', max_length=50, blank=True, null=True)  # Field name made lowercase.
    quantity = models.IntegerField(db_column='Quantity', blank=True, null=True)  # Field name made lowercase.
    purchaseprice = models.FloatField(db_column='PurchasePrice', blank=True, null=True)  # Field name made lowercase.
    totalcost = models.FloatField(db_column='TotalCost', blank=True, null=True, editable=False)  # Field name made lowercase.

    class Meta:
        db_table = 'STATZ_WAREHOUSE_INVENTORY_TBL'

        def __str__(self):
            return self.db_table

    def save(self, *args, **kwargs):
        self.totalcost = self.purchaseprice * self.quantity
        super().save(*args, **kwargs)
