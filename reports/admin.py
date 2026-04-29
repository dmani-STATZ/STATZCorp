from django.contrib import admin

from .models import Report, ReportDraft, ReportRequest, ReportShare, ReportVersion


@admin.register(ReportRequest)
class ReportRequestAdmin(admin.ModelAdmin):
    list_display = ("requester", "status", "is_branch_request", "keep_original", "created_at")
    list_filter = ("status", "is_branch_request")
    search_fields = ("requester__username", "description")
    readonly_fields = ("created_at", "updated_at", "is_branch_request", "parent_version")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "visibility", "source", "branch_count", "created_at")
    list_filter = ("visibility", "source")
    search_fields = ("title", "owner__username")
    readonly_fields = ("created_at", "updated_at", "branch_count")


@admin.register(ReportVersion)
class ReportVersionAdmin(admin.ModelAdmin):
    list_display = ("report", "version_number", "created_by", "created_at")
    readonly_fields = ("created_at", "version_number")


@admin.register(ReportShare)
class ReportShareAdmin(admin.ModelAdmin):
    list_display = ("report", "shared_by", "shared_with", "can_branch", "created_at")
    readonly_fields = ("created_at",)


@admin.register(ReportDraft)
class ReportDraftAdmin(admin.ModelAdmin):
    list_display = ("owner", "current_title", "ai_iteration_count", "created_at")
    readonly_fields = ("created_at", "updated_at", "ai_iteration_count")
