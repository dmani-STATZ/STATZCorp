from django import forms
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import (
    Nsn, Supplier, Contract, Clin, Note, Reminder,
    ClinAcknowledgment, AcknowledgementLetter, Contact, Address,
    Buyer, ContractType, ClinType, CanceledReason, SalesClass,
    SpecialPaymentTerms, IdiqContract, IdiqContractDetails, SupplierType, SupplierCertification,
    CertificationType, SupplierClassification,
    ClassificationType, FolderTracking
)

User = get_user_model()

class ActiveUserModelChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, **kwargs):
        if 'queryset' not in kwargs:
            kwargs['queryset'] = User.objects.filter(is_active=True).order_by('username')
        if 'widget' not in kwargs:
            kwargs['widget'] = forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            })
        super().__init__(*args, **kwargs)

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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            }),
            
            # Address Information
            'physical_address': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
            }),
            'shipping_address': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
            }),
            'billing_address': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
            }),
            
            # Additional Information - Checkboxes
            'probation': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'conditional': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'special_terms': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
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
    assigned_user = ActiveUserModelChoiceField(
        required=False,
        empty_label="Select User",
    )
    reviewed_by = ActiveUserModelChoiceField(
        required=False,
        empty_label="Select User",
    )

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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            }),
            'contract_number': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Contract Number'
            }),
            'status': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            }),
            'contract_type': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            }),
            'survey_date': forms.DateInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'date'
            }),
            'survey_type': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Survey Type'
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
            'reviewed_on': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            }),
        }

class ClinForm(forms.ModelForm):
    class Meta:
        model = Clin
        fields = [
            'contract', 'po_num_ext', 'tab_num', 
            'clin_po_num', 'po_number', 'clin_type', 'supplier', 
            'nsn', 'ia', 'fob', 'order_qty', 'ship_qty', 
            'due_date', 'supplier_due_date', 'ship_date',
            'special_payment_terms', 'special_payment_terms_paid', 
            'quote_value', 'paid_amount', 
            'paid_date', 'wawf_payment', 'wawf_recieved', 
            'wawf_invoice', 'plan_gross', 'planned_split',
            'ppi_split', 'statz_split', 'ppi_split_paid', 'statz_split_paid',
            'item_number', 'item_type', 'item_value'
        ]
        widgets = {
            'contract': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
            }),
            'supplier': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
            }),
            'nsn': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
            }),
            'ia': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
            }),
            'fob': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none',
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            }),
            'special_payment_terms_paid': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            }),
            'contract_value': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Contract Value',
                'step': '0.01'
            }),
            'quote_value': forms.NumberInput(attrs={
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
            'ppi_split': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter PPI Split',
                'step': '0.01'
            }),
            'statz_split': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter STATZ Split',
                'step': '0.01'
            }),
            'ppi_split_paid': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter PPI Split Paid',
                'step': '0.01'
            }),
            'statz_split_paid': forms.NumberInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter STATZ Split Paid',
                'step': '0.01'
            })
        }
        
    def __init__(self, *args, **kwargs):
        """
        Initialize the form with querysets for foreign key fields.
        """
        super().__init__(*args, **kwargs)
        
        # For new forms, initialize with appropriate querysets
        if not kwargs.get('instance'):
            # If we have a contract_id in initial data, pre-select it
            contract_id = kwargs.get('initial', {}).get('contract')
            if contract_id:
                self.fields['contract'].queryset = Contract.objects.filter(id=contract_id)
            else:
                # Load all contracts
                self.fields['contract'].queryset = Contract.objects.all().order_by('contract_number')
                
            # Load all options for other foreign key fields
            self.fields['clin_type'].queryset = ClinType.objects.all().order_by('description')
            self.fields['special_payment_terms'].queryset = SpecialPaymentTerms.objects.all().order_by('terms')
            
            # NSN and Supplier are handled via custom modal UI, so we keep them empty
            # but don't make them required in the form (will be validated in the view)
            self.fields['supplier'].queryset = Supplier.objects.none()
            self.fields['supplier'].required = False
            self.fields['nsn'].queryset = Nsn.objects.none()
            self.fields['nsn'].required = False
            
            # If we have POST data (form validation failed), try to load the selected NSN and Supplier
            if args and args[0] and isinstance(args[0], dict) and 'nsn' in args[0] and 'supplier' in args[0]:
                # Form validation failed and we need to re-populate the NSN and Supplier querysets
                nsn_id = args[0].get('nsn')
                supplier_id = args[0].get('supplier')
                
                if nsn_id:
                    try:
                        self.fields['nsn'].queryset = Nsn.objects.filter(id=nsn_id)
                        # Store the NSN instance for template access
                        self.nsn_value = Nsn.objects.get(id=nsn_id)
                    except (Nsn.DoesNotExist, ValueError):
                        pass
                
                if supplier_id:
                    try:
                        self.fields['supplier'].queryset = Supplier.objects.filter(id=supplier_id)
                        # Store the Supplier instance for template access
                        self.supplier_value = Supplier.objects.get(id=supplier_id)
                    except (Supplier.DoesNotExist, ValueError):
                        pass
        else:
            # For existing instances, load all options but ensure the selected value is included
            instance = kwargs['instance']
            
            # Load all contracts
            self.fields['contract'].queryset = Contract.objects.all().order_by('contract_number')
            
            # Load all CLIN types
            self.fields['clin_type'].queryset = ClinType.objects.all().order_by('description')
            
            # Load all special payment terms
            self.fields['special_payment_terms'].queryset = SpecialPaymentTerms.objects.all().order_by('terms')
            
            # NSN and Supplier are handled via custom modal UI
            # Only include the currently selected value if it exists
            if instance.supplier_id:
                self.fields['supplier'].queryset = Supplier.objects.filter(id=instance.supplier_id)
            else:
                self.fields['supplier'].queryset = Supplier.objects.none()
                
            if instance.nsn_id:
                self.fields['nsn'].queryset = Nsn.objects.filter(id=instance.nsn_id)
            else:
                self.fields['nsn'].queryset = Nsn.objects.none()
                
    def clean(self):
        """
        Custom clean method to handle NSN and Supplier validation.
        """
        cleaned_data = super().clean()
        
        # Skip the default field validation for nsn and supplier
        # They will be validated and processed in the view
        if 'nsn' in self._errors:
            # We handle NSN validation in the view, so remove the error here
            del self._errors['nsn']
            
        if 'supplier' in self._errors:
            # We handle Supplier validation in the view, so remove the error here
            del self._errors['supplier']
            
        return cleaned_data

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
    assigned_to = ActiveUserModelChoiceField(
        required=False,
        empty_label="Select User",
    )
    
    class Meta:
        model = Reminder
        fields = ['reminder_title', 'reminder_text', 'reminder_date', 'reminder_user', 'reminder_completed']
        widgets = {
            'reminder_title': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter title'
            }),
            'reminder_text': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter description',
                'rows': 3
            }),
            'reminder_date': forms.DateTimeInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'type': 'datetime-local'
            }),
            'reminder_user': forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            }),
            'reminder_completed': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500'
            })
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

class AcknowledgementLetterForm(forms.ModelForm):
    class Meta:
        model = AcknowledgementLetter
        fields = [
            'letter_date',
            'salutation',
            'addr_fname',
            'addr_lname',
            'supplier',
            'st_address',
            'city',
            'state',
            'zip',
            'po',
            'po_ext',
            'contract_num',
            'statz_contact',
            'statz_contact_title',
            'statz_contact_phone',
            'statz_contact_email',
            'fat_plt_due_date',
            'supplier_due_date',
            'dpas_priority',
        ]
        widgets = {
            'letter_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'salutation': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Salutation'
            }),
            'addr_fname': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter First Name'
            }),
            'addr_lname': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Last Name'
            }),
            'supplier': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Supplier'
            }),
            'st_address': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Street Address'
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
            'po': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter PO Number'
            }),
            'po_ext': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter PO Extension'
            }),
            'contract_num': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter Contract Number'
            }),
            'statz_contact': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter STATZ Contact'
            }),
            'statz_contact_title': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter STATZ Contact Title'
            }),
            'statz_contact_phone': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter STATZ Contact Phone'
            }),
            'statz_contact_email': forms.EmailInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter STATZ Contact Email'
            }),
            'fat_plt_due_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'supplier_due_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500'
            }),
            'dpas_priority': forms.TextInput(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'placeholder': 'Enter DPAS Priority'
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
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
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500',
                'rows': 3,
                'placeholder': 'Enter Notes'
            }),
        }

class ContractSearchForm(forms.Form):
    search_query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by Contract Number or PO Number...',
            'hx-get': '/contracts/folder-tracking/search/',
            'hx-trigger': 'keyup changed delay:500ms',
            'hx-target': '#search-results'
        })
    )

class FolderTrackingForm(forms.ModelForm):
    class Meta:
        model = FolderTracking
        fields = ['contract']
        widgets = {
            'contract': forms.HiddenInput()
        }

class IdiqContractForm(forms.ModelForm):
    class Meta:
        model = IdiqContract
        fields = [
            'contract_number',
            'buyer',
            'award_date',
            'term_length',
            'option_length',
            'closed',
            'tab_num'
        ]
        widgets = {
            'award_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'term_length': forms.NumberInput(attrs={'min': 0}),
            'option_length': forms.NumberInput(attrs={'min': 0}),
        }

class IdiqContractDetailsForm(forms.ModelForm):
    class Meta:
        model = IdiqContractDetails
        fields = ['nsn', 'supplier']
        widgets = {
            'nsn': forms.Select(attrs={'class': 'select2'}),
            'supplier': forms.Select(attrs={'class': 'select2'}),
        } 