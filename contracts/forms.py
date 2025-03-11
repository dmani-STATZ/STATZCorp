from django import forms
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from .models import (
    Nsn, Supplier, Contract, Clin, Note, Reminder,
    ClinAcknowledgment, AcknowledgementLetter, Contact, Address,
    Buyer, ContractType, ClinType, CanceledReason, SalesClass,
    SpecialPaymentTerms, IdiqContract, IdiqContractDetails, SupplierType, SupplierCertification,
    CertificationType, CertificationStatus, SupplierClassification,
    ClassificationType
)

class NsnForm(forms.ModelForm):
    class Meta:
        model = Nsn
        fields = ['nsn_code', 'description', 'part_number', 'revision', 'notes', 'directory_url']
        widgets = {
            'nsn_code': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter NSN Code'
            }),
            'description': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Description'
            }),
            'part_number': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Part Number'
            }),
            'revision': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Revision'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'rows': 4,
                'placeholder': 'Enter Notes'
            }),
            'directory_url': forms.URLInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Directory URL'
            }),
        }

class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            'name', 'cage_code', 'supplier_type', 'billing_address', 'shipping_address',
            'physical_address', 'business_phone', 'business_fax', 'business_email',
            'contact', 'probation', 'conditional', 'special_terms', 'prime', 'ppi',
            'iso', 'notes', 'allows_gsi', 'is_packhouse', 'packhouse'
        ]
        widgets = {
            # Basic Information
            'name': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Supplier Name'
            }),
            'cage_code': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter CAGE Code'
            }),
            'supplier_type': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            
            # Address Information
            'physical_address': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'shipping_address': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'billing_address': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            
            # Contact Information
            'business_phone': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Business Phone',
                'type': 'tel'
            }),
            'business_fax': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Business Fax',
                'type': 'tel'
            }),
            'business_email': forms.EmailInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Business Email'
            }),
            'contact': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            
            # Additional Information - Checkboxes
            'probation': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'conditional': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'special_terms': forms.Select(attrs={
                'class': 'w-40 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'prime': forms.TextInput(attrs={
                'class': 'w-10 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'ppi': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'iso': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'allows_gsi': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'is_packhouse': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'packhouse': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'rows': 4,
                'placeholder': 'Enter Notes'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sort select field choices
        if 'packhouse' in self.fields:
            self.fields['packhouse'].queryset = self.fields['packhouse'].queryset.order_by('name')
        if 'contact' in self.fields:
            self.fields['contact'].queryset = self.fields['contact'].queryset.order_by('name')

class ContractForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = [
            'idiq_contract', 'contract_number', 'status', 'open', 'date_closed',
            'cancelled', 'date_canceled', 'canceled_reason', 'po_number', 'tab_num',
            'buyer', 'contract_type', 'award_date', 'due_date', 'due_date_late',
            'sales_class', 'survey_date', 'survey_type', 'assigned_user',
            'assigned_date', 'nist', 'files_url', 'reviewed', 'reviewed_by',
            'reviewed_on', 'contract_value'
        ]
        widgets = {
            'idiq_contract': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'contract_number': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Contract Number'
            }),
            'status': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'open': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'date_closed': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'cancelled': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'date_canceled': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'canceled_reason': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'po_number': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter PO Number'
            }),
            'tab_num': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Tab Number'
            }),
            'buyer': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'contract_type': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'award_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'due_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'due_date_late': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'sales_class': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'survey_date': forms.DateInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'date'
            }),
            'survey_type': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Survey Type'
            }),
            'assigned_user': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Assigned User'
            }),
            'assigned_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'nist': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'files_url': forms.URLInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Files URL'
            }),
            'reviewed': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'reviewed_by': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Reviewer Name'
            }),
            'reviewed_on': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'statz_value': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter STATZ Value',
                'step': '0.01'
            }),
            'contract_value': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter 1155 Total Value',
                'step': '0.01'
            }),
        }

    def clean_contract_number(self):
        contract_number = self.cleaned_data.get('contract_number')
        if contract_number:
            # Check if this is an update to an existing contract
            instance = getattr(self, 'instance', None)
            if instance and instance.pk:
                # If updating, exclude the current instance from the check
                exists = Contract.objects.exclude(pk=instance.pk).filter(contract_number=contract_number).exists()
            else:
                # If creating new, check all contracts
                exists = Contract.objects.filter(contract_number=contract_number).exists()
            
            if exists:
                raise forms.ValidationError('A contract with this number already exists.')
        return contract_number

class ContractCloseForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = ['open', 'date_closed']
        widgets = {
            'open': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'date_closed': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
        }

class ContractCancelForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = ['cancelled', 'date_canceled', 'canceled_reason']
        widgets = {
            'cancelled': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'date_canceled': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'canceled_reason': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
        }

class ClinForm(forms.ModelForm):
    class Meta:
        model = Clin
        fields = [
            'contract', 'sub_contract', 'po_num_ext', 'tab_num', 
            'clin_po_num', 'po_number', 'clin_type', 'supplier', 
            'nsn', 'ia', 'fob', 'order_qty', 'ship_qty', 
            'due_date', 'supplier_due_date', 'ship_date',
            'special_payment_terms', 'special_payment_terms_paid', 
            'contract_value', 'po_amount', 'paid_amount', 
            'paid_date', 'wawf_payment', 'wawf_recieved', 
            'wawf_invoice', 'plan_gross', 'planned_split'
        ]
        widgets = {
            'contract': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'sub_contract': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Sub Contract'
            }),
            'po_num_ext': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter PO Number Extension'
            }),
            'tab_num': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Tab Number'
            }),
            'clin_po_num': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter CLIN PO Number'
            }),
            'po_number': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter PO Number'
            }),
            'clin_type': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'supplier': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'nsn': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'ia': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
            }),
            'fob': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
            }),
            'order_qty': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Order Quantity'
            }),
            'ship_qty': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Ship Quantity'
            }),
            'due_date': forms.DateInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'date'
            }),
            'supplier_due_date': forms.DateInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'date'
            }),
            'ship_date': forms.DateInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'date'
            }),
            'special_payment_terms': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'special_payment_terms_paid': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'contract_value': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Contract Value',
                'step': '0.0001'
            }),
            'po_amount': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter PO Amount',
                'step': '0.0001'
            }),
            'paid_amount': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Paid Amount',
                'step': '0.0001'
            }),
            'paid_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'wawf_payment': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter WAWF Payment',
                'step': '0.0001'
            }),
            'wawf_recieved': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'wawf_invoice': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter WAWF Invoice'
            }),
            'plan_gross': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Plan Gross',
                'step': '0.0001'
            }),
            'planned_split': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Planned Split'
            }),
        }
        
    def __init__(self, *args, **kwargs):
        """
        Initialize the form with optimized querysets for foreign key fields.
        This helps reduce the load time by limiting the initial data loaded.
        """
        super().__init__(*args, **kwargs)
        
        # For new forms, initialize with empty querysets for foreign key fields
        # These will be populated asynchronously via JavaScript
        if not kwargs.get('instance'):
            # If we have a contract_id in initial data, keep it
            contract_id = kwargs.get('initial', {}).get('contract')
            if contract_id:
                self.fields['contract'].queryset = Contract.objects.filter(id=contract_id)
            else:
                self.fields['contract'].queryset = Contract.objects.none()
                
            # Initialize other foreign key fields with empty querysets
            self.fields['clin_type'].queryset = ClinType.objects.none()
            self.fields['supplier'].queryset = Supplier.objects.none()
            self.fields['nsn'].queryset = Nsn.objects.none()
            self.fields['special_payment_terms'].queryset = SpecialPaymentTerms.objects.none()
        else:
            # For existing instances, only load the currently selected values
            instance = kwargs['instance']
            
            if instance.contract_id:
                self.fields['contract'].queryset = Contract.objects.filter(id=instance.contract_id)
            else:
                self.fields['contract'].queryset = Contract.objects.none()
                
            if instance.clin_type_id:
                self.fields['clin_type'].queryset = ClinType.objects.filter(id=instance.clin_type_id)
            else:
                self.fields['clin_type'].queryset = ClinType.objects.none()
                
            if instance.supplier_id:
                self.fields['supplier'].queryset = Supplier.objects.filter(id=instance.supplier_id)
            else:
                self.fields['supplier'].queryset = Supplier.objects.none()
                
            if instance.nsn_id:
                self.fields['nsn'].queryset = Nsn.objects.filter(id=instance.nsn_id)
            else:
                self.fields['nsn'].queryset = Nsn.objects.none()
                
            if instance.special_payment_terms_id:
                self.fields['special_payment_terms'].queryset = SpecialPaymentTerms.objects.filter(id=instance.special_payment_terms_id)
            else:
                self.fields['special_payment_terms'].queryset = SpecialPaymentTerms.objects.none()

class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ['note']
        widgets = {
            'note': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'rows': 4,
                'placeholder': 'Enter Note'
            }),
        }

class ReminderForm(forms.ModelForm):
    class Meta:
        model = Reminder
        fields = ['reminder_title', 'reminder_text', 'reminder_date']
        widgets = {
            'reminder_title': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Reminder Title'
            }),
            'reminder_text': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'rows': 3,
                'placeholder': 'Enter Reminder Details'
            }),
            'reminder_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
        }

class ClinAcknowledgmentForm(forms.ModelForm):
    class Meta:
        model = ClinAcknowledgment
        fields = [
            'po_to_supplier_bool', 'po_to_supplier_date',
            'clin_reply_bool', 'clin_reply_date',
            'po_to_qar_bool', 'po_to_qar_date'
        ]
        widgets = {
            'po_to_supplier_bool': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'po_to_supplier_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'clin_reply_bool': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'clin_reply_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'po_to_qar_bool': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'po_to_qar_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
        }

class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['address_line_1', 'address_line_2', 'city', 'state', 'zip']
        widgets = {
            'address_line_1': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Address Line 1'
            }),
            'address_line_2': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Address Line 2'
            }),
            'city': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter City'
            }),
            'state': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter State'
            }),
            'zip': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter ZIP Code'
            }),
        }

class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['salutation', 'name', 'company', 'title', 'phone', 'email', 'address', 'notes']
        widgets = {
            'salutation': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'name': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Name'
            }),
            'company': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Company'
            }),
            'title': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Title'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Phone',
                'type': 'tel'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Email'
            }),
            'address': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'rows': 3,
                'placeholder': 'Enter Notes'
            }),
        } 