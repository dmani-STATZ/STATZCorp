from django.contrib import admin

from sales.models import SupplierRFQ


@admin.register(SupplierRFQ)
class SupplierRFQAdmin(admin.ModelAdmin):
    list_display = ("pk", "supplier", "line", "status", "sent_at", "send_attempts")
    list_filter = ("status",)
    search_fields = ("supplier__name", "supplier__cage_code")
    readonly_fields = ("send_attempts", "last_send_error")
