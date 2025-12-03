from django.contrib import admin

from .models import Contact, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'cage_code', 'dodaac', 'supplier_type', 'archived')
    search_fields = ('name', 'cage_code', 'dodaac')
    list_filter = ('archived', 'supplier_type')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'email', 'phone', 'supplier')
    search_fields = ('name', 'company', 'email', 'supplier__name')
