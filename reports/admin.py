from django.contrib import admin
from .models import ReportRequest


@admin.register(ReportRequest)
class ReportRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "category", "status", "created_at")
    list_filter = ("status", "category", "created_at")
    search_fields = ("title", "description", "user__username", "user__email")
    readonly_fields = ("created_at", "updated_at", "last_run_at", "last_run_rowcount")

# Register your models here.
