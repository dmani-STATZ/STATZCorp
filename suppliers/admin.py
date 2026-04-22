from django.contrib import admin

from .models import (
    CertificationType,
    ClassificationType,
    Contact,
    Supplier,
    SupplierContactGroup,
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


@admin.register(SupplierContactGroup)
class SupplierContactGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'supplier', 'contact_count', 'created_on')
    search_fields = ('name', 'supplier__name')
    list_filter = ('supplier',)
    filter_horizontal = ('contacts',)

    def contact_count(self, obj):
        return obj.contacts.count()
    contact_count.short_description = 'Contacts'


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
