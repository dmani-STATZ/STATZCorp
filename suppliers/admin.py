from django.contrib import admin

from .models import Contact, Supplier


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
