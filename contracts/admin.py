from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import (
    CanceledReason,
    ClinReclassificationDraft,
    ClinReclassificationLog,
    ClinShipment,
    ClinSplit,
    ClinType,
    Company,
    CompanyPOProfile,
    Contract,
    ContractFinanceLine,
    ContractStatus,
    ContractStatusHistory,
    ContractType,
    DfasImportBatch,
    DfasImportRow,
    FinanceLinePayment,
    FinanceLineType,
    POLineItem,
    POSnippet,
    PurchaseOrder,
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
    list_display = ('name', 'slug', 'is_active', 'enable_po_generator', 'sharepoint_site_name')
    search_fields = ('name', 'slug')
    list_filter = ('is_active',)
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'is_active', 'enable_po_generator', 'logo', 'primary_color', 'secondary_color')}),
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


@admin.register(ContractStatusHistory)
class ContractStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('contract', 'from_status', 'to_status', 'changed_by', 'changed_at')
    list_filter = ('to_status',)
    search_fields = ('contract__contract_number',)
    readonly_fields = ('id', 'contract', 'from_status', 'to_status', 'changed_by', 'changed_at', 'reason')


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


@admin.register(ClinShipment)
class ClinShipmentAdmin(admin.ModelAdmin):
    list_display = ['clin', 'ship_date', 'ship_qty', 'uom',
                    'quote_value', 'item_value', 'paid_amount', 'wawf_payment']
    list_filter = ['ship_date']
    search_fields = ['clin__item_number', 'clin__contract__contract_number']


@admin.register(FinanceLineType)
class FinanceLineTypeAdmin(admin.ModelAdmin):
    pass


@admin.register(ContractFinanceLine)
class ContractFinanceLineAdmin(admin.ModelAdmin):
    pass


@admin.register(FinanceLinePayment)
class FinanceLinePaymentAdmin(admin.ModelAdmin):
    pass


@admin.register(DfasImportBatch)
class DfasImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'filename', 'company', 'uploaded_by', 'uploaded_at',
        'status', 'row_count', 'imported_count', 'skipped_count',
        'duplicate_count', 'unmatched_count', 'error_count',
    )
    list_filter = ('status', 'company', 'uploaded_at')
    search_fields = ('filename', 'uploaded_by__username')
    readonly_fields = tuple(f.name for f in DfasImportBatch._meta.fields)
    ordering = ('-uploaded_at',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DfasImportRow)
class DfasImportRowAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'batch', 'raw_contract_no', 'raw_call_no', 'raw_clin',
        'raw_invoice_no', 'raw_check_eft_amount', 'status',
        'matched_contract', 'matched_clin',
    )
    list_filter = ('status', 'batch')
    search_fields = (
        'raw_contract_no', 'raw_call_no', 'raw_invoice_no',
        'raw_voucher_no', 'match_notes',
    )
    readonly_fields = tuple(f.name for f in DfasImportRow._meta.fields)
    ordering = ('batch', 'id')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# =============================================================================
# CLIN Fix Tool (sunset cleanup) — see CONTEXT.md / AGENTS.md
# =============================================================================


@admin.register(ClinReclassificationLog)
class ClinReclassificationLogAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'contract', 'original_clin_id', 'destination_type',
        'destination_id', 'notes_migrated_count',
        'payment_history_deleted_count', 'performed_by', 'performed_at',
    )
    list_filter = ('destination_type', 'performed_at')
    search_fields = ('contract__contract_number', 'original_clin_id')
    readonly_fields = tuple(f.name for f in ClinReclassificationLog._meta.fields)
    ordering = ('-performed_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(POSnippet)
class POSnippetAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'sort_order', 'company')
    list_filter = ('company', 'category')
    search_fields = ('title', 'body', 'category')
    ordering = ('company', 'category', 'sort_order', 'title')


@admin.register(ClinReclassificationDraft)
class ClinReclassificationDraftAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'contract', 'clin', 'user', 'destination_type',
        'parent_clin', 'updated_at',
    )
    list_filter = ('destination_type', 'updated_at')
    search_fields = (
        'contract__contract_number', 'user__username',
        'clin__item_number',
    )
    ordering = ('-updated_at',)


class POLineItemInline(admin.TabularInline):
    model = POLineItem
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('po_number', 'contract', 'supplier', 'po_date', 'modified_on')
    search_fields = ('po_number', 'contract__contract_number')
    inlines = [POLineItemInline]
    autocomplete_fields = ()
    raw_id_fields = ('contract', 'supplier', 'company')
    fields = (
        'company', 'contract', 'supplier', 'po_number', 'po_date',
        'vendor_name', 'vendor_address', 'ship_to_name', 'ship_to_contact', 'footer'
    )


@admin.register(CompanyPOProfile)
class CompanyPOProfileAdmin(admin.ModelAdmin):
    list_display = ('company', 'ship_to_name', 'cage_code')
