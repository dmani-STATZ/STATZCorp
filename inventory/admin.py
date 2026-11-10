from django.contrib import admin

from .models import InventoryItem, InventorySyncRun

admin.site.register(InventoryItem)


@admin.register(InventorySyncRun)
class InventorySyncRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'created_by', 'original_filename', 'status', 'applied_at')
    list_filter = ('status',)
    exclude = ('file_bytes',)
    readonly_fields = (
        'created_at', 'created_by', 'original_filename', 'status',
        'plan', 'errors', 'warnings', 'applied_at',
    )

    def get_queryset(self, request):
        return super().get_queryset(request).defer('file_bytes').select_related('created_by')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
