from django.contrib import admin

from tools.models import ScanFilingLog


@admin.register(ScanFilingLog)
class ScanFilingLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "user",
        "contract_number",
        "attachment_name",
        "uploaded_name",
    )
    list_filter = ("action", "created_at")
    search_fields = (
        "message_id",
        "contract_number",
        "attachment_name",
        "uploaded_name",
    )
    readonly_fields = tuple(f.name for f in ScanFilingLog._meta.fields)
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
