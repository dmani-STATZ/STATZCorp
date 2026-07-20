from django.contrib import admin

from .models import (
    CertificationType,
    ClassificationType,
    Contact,
    Supplier,
    SupplierContactCategory,
    SupplierPortalChangeLog,
    SupplierType,
)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'cage_code', 'dodaac', 'supplier_type', 'primary_phone', 'primary_email', 'website_url', 'archived')
    search_fields = ('name', 'cage_code', 'dodaac', 'primary_phone', 'primary_email', 'website_url')
    list_filter = ('archived', 'supplier_type')
    fieldsets = (
        (None, {
            "fields": ("name", "cage_code", "dodaac", "supplier_type")
        }),
        ("Contact", {
            "fields": ("primary_phone", "primary_email", "business_phone", "business_email", "website_url")
        }),
        ("Branding", {
            "fields": ("logo_url",)
        }),
        ("Addresses", {
            "fields": ("billing_address", "shipping_address", "physical_address")
        }),
        ("Compliance & Status", {
            "fields": ("probation", "probation_on", "conditional", "conditional_on", "archived", "archived_on")
        }),
        ("Metadata", {
            "fields": ("last_enriched_at",)
        }),
    )


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'email', 'phone', 'supplier')
    search_fields = ('name', 'company', 'email', 'supplier__name')
    filter_horizontal = ('categories',)


@admin.register(SupplierContactCategory)
class SupplierContactCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'sort_order')
    list_editable = ('is_active', 'sort_order')
    search_fields = ('name',)


@admin.register(SupplierType)
class SupplierTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'description')
    search_fields = ('code', 'description')


@admin.register(CertificationType)
class CertificationTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name')
    search_fields = ('code', 'name')


@admin.register(ClassificationType)
class ClassificationTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(SupplierPortalChangeLog)
class SupplierPortalChangeLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'cage_code', 'action', 'entity_type', 'entity_id', 'supplier')
    list_filter = ('action', 'entity_type', 'created_at')
    search_fields = ('cage_code', 'supplier__name')
    readonly_fields = (
        'supplier',
        'cage_code',
        'action',
        'entity_type',
        'entity_id',
        'changes',
        'created_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
