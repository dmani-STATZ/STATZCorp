from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import (
    CanceledReason,
    ClinSplit,
    ClinType,
    Company,
    Contract,
    ContractStatus,
    ContractType,
    Reminder,
    SalesClass,
    SpecialPaymentTerms,
)

User = get_user_model()

class ActiveUserAdminMixin:
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in ['assigned_user', 'reviewed_by', 'reminder_user', 'reminder_completed_user']:
            kwargs['queryset'] = User.objects.filter(is_active=True).order_by('username')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(Contract)
class ContractAdmin(ActiveUserAdminMixin, admin.ModelAdmin):
    list_display = ['contract_number', 'po_number', 'status', 'assigned_user', 'reviewed_by']
    search_fields = ['contract_number', 'po_number']
    list_filter = ['status', 'assigned_user', 'reviewed_by']


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'sharepoint_site_name')
    search_fields = ('name', 'slug')
    list_filter = ('is_active',)
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'is_active', 'logo', 'primary_color', 'secondary_color')}),
        ('SharePoint documents', {
            'fields': ('sharepoint_base_url', 'sharepoint_site_name', 'sharepoint_documents_path'),
            'description': 'Base URL down to /sites/ (e.g. https://statzcorpgcch.sharepoint.us/sites). '
                         'Site name: Statz, JVIC. Documents path: folder under Shared Documents (e.g. Statz-Public/data/V87/aFed-DOD).',
        }),
    )

@admin.register(Reminder)
class ReminderAdmin(ActiveUserAdminMixin, admin.ModelAdmin):
    list_display = ['reminder_title', 'reminder_date', 'reminder_user', 'reminder_completed']
    search_fields = ['reminder_title', 'reminder_text']
    list_filter = ['reminder_completed', 'reminder_user']


@admin.register(CanceledReason)
class CanceledReasonAdmin(admin.ModelAdmin):
    list_display = ('id', 'description')
    search_fields = ('description',)


@admin.register(ClinType)
class ClinTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'description', 'raw_text')
    search_fields = ('description', 'raw_text')


@admin.register(ContractStatus)
class ContractStatusAdmin(admin.ModelAdmin):
    list_display = ('id', 'description')
    search_fields = ('description',)


@admin.register(ContractType)
class ContractTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'description')
    search_fields = ('description',)


@admin.register(SalesClass)
class SalesClassAdmin(admin.ModelAdmin):
    list_display = ('id', 'sales_team')
    search_fields = ('sales_team',)


@admin.register(SpecialPaymentTerms)
class SpecialPaymentTermsAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'terms')
    search_fields = ('code', 'terms')


@admin.register(ClinSplit)
class ClinSplitAdmin(admin.ModelAdmin):
    list_display = ('id', 'clin', 'company_name', 'split_value', 'split_paid')
    list_filter = ('company_name',)
    search_fields = ('company_name',)
