from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "content_type", "object_id", "field_name", "old_value", "new_value", "created_at", "user")
    list_filter = ("content_type", "created_at")
    search_fields = ("field_name", "old_value", "new_value")
    readonly_fields = ("content_type", "object_id", "field_name", "old_value", "new_value", "created_at", "user")
    date_hierarchy = "created_at"
