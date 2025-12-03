from django.contrib import admin

from .models import Nsn, SupplierNSNCapability


@admin.register(Nsn)
class NsnAdmin(admin.ModelAdmin):
    list_display = ('nsn_code', 'description', 'part_number', 'revision')
    search_fields = ('nsn_code', 'description', 'part_number')


@admin.register(SupplierNSNCapability)
class SupplierNSNCapabilityAdmin(admin.ModelAdmin):
    list_display = ('nsn', 'supplier', 'lead_time_days', 'price_reference')
    search_fields = ('nsn__nsn_code', 'supplier__name')
