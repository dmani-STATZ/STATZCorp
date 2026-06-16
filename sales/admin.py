from django.contrib import admin

from sales.models import DibbsNotice, SupplierRFQ


@admin.register(DibbsNotice)
class DibbsNoticeAdmin(admin.ModelAdmin):
    list_display = ["title", "posted_date", "discovered_at"]
    list_filter = ["posted_date"]
    search_fields = ["title"]
    readonly_fields = ["discovered_at"]
    ordering = ["-posted_date"]


@admin.register(SupplierRFQ)
class SupplierRFQAdmin(admin.ModelAdmin):
    list_display = ("pk", "supplier", "line", "status", "sent_at", "send_attempts")
    list_filter = ("status",)
    search_fields = ("supplier__name", "supplier__cage_code")
    readonly_fields = ("send_attempts", "last_send_error")
