from django.contrib import admin

from dibbs.models import DibbsNotice


@admin.register(DibbsNotice)
class DibbsNoticeAdmin(admin.ModelAdmin):
    list_display = ["title", "posted_date", "discovered_at"]
    list_filter = ["posted_date"]
    search_fields = ["title"]
    readonly_fields = ["discovered_at"]
    ordering = ["-posted_date"]
