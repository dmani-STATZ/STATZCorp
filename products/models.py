from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from suppliers.models import Supplier


class AuditModel(models.Model):
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products_%(class)s_created',
    )
    created_on = models.DateTimeField(default=timezone.now)
    modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products_%(class)s_modified',
    )
    modified_on = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.id:
            self.created_on = timezone.now()
        self.modified_on = timezone.now()
        super().save(*args, **kwargs)


class Nsn(AuditModel):
    nsn_code = models.CharField(max_length=20, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    part_number = models.CharField(max_length=25, null=True, blank=True)
    revision = models.CharField(max_length=25, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    directory_url = models.CharField(max_length=200, null=True, blank=True)
    suppliers = models.ManyToManyField(
        Supplier,
        related_name='capable_nsns',
        through='SupplierNSNCapability',
    )

    class Meta:
        db_table = 'contracts_nsn'

    def __str__(self):
        return f"NSN {self.nsn_code}"


class SupplierNSNCapability(models.Model):
    nsn = models.ForeignKey(Nsn, on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    lead_time_days = models.IntegerField(null=True, blank=True)
    price_reference = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'supplier_nsn_capability'
