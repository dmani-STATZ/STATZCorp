from django import forms
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.models import UserCompanyMembership
from products.models import Nsn
from suppliers.models import (
    Supplier,
    Contact,
    SupplierType,
    SupplierCertification,
    SupplierClassification,
    CertificationType,
    ClassificationType,
)
from .models import (
    Contract,
    Clin,
    Note,
    Reminder,
    ClinAcknowledgment,
    AcknowledgementLetter,
    Address,
    Buyer,
    ContractType,
    ClinType,
    CanceledReason,
    SalesClass,
    SpecialPaymentTerms,
    IdiqContract,
    IdiqContractDetails,
    FolderTracking,
    Company,
)

User = get_user_model()

class BaseFormMixin:
    """
    Base form mixin that provides consistent styling for all form widgets.
    This implements the form-styling-rule for the application.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
    
    def _style_fields(self):
        """Apply consistent styling to all form fields based on their widget type."""
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.TextInput, forms.NumberInput, 
                                forms.EmailInput, forms.URLInput, forms.DateInput, 
                                forms.DateTimeInput, forms.TimeInput)):
                widget.attrs['class'] = 'form-input'
            elif isinstance(widget, forms.Select):
                widget.attrs['class'] = 'form-select'
            elif isinstance(widget, forms.Textarea):
                widget.attrs['class'] = 'form-input'
                if 'rows' not in widget.attrs:
                    widget.attrs['rows'] = 3
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'form-checkbox'
            
            # Add placeholder if not present
            if not widget.attrs.get('placeholder') and field.label:
                widget.attrs['placeholder'] = f'Enter {field.label}'

class BaseModelForm(BaseFormMixin, forms.ModelForm):
    """Base ModelForm that implements the form-styling-rule."""
    pass

class BaseForm(BaseFormMixin, forms.Form):
    """Base Form that implements the form-styling-rule."""
    pass

class ActiveUserModelChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, **kwargs):
        if 'queryset' not in kwargs:
            kwargs['queryset'] = User.objects.filter(is_active=True).order_by('username')
        if 'widget' not in kwargs:
            kwargs['widget'] = forms.Select(attrs={
                'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 py-2 px-3 h-[38px] appearance-none'
            })
        super().__init__(*args, **kwargs)

class NsnForm(BaseModelForm):
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

class SupplierForm(BaseModelForm):
    class Meta:
        model = Supplier
        fields = [
            'name', 'cage_code', 'supplier_type', 'billing_address', 'shipping_address',
            'physical_address', 'business_phone', 'business_fax', 'business_email',
            'primary_phone', 'primary_email', 'website_url', 'logo_url',
            'contact', 'probation', 'conditional', 'special_terms', 'prime', 'ppi',
            'iso', 'notes', 'allows_gsi', 'is_packhouse', 'packhouse', 'archived'
        ]
        widgets = {
            'business_phone': forms.TextInput(attrs={
                'type': 'tel'
            }),
            'business_fax': forms.TextInput(attrs={
                'type': 'tel'
            }),
            'primary_phone': forms.TextInput(attrs={
                'type': 'tel'
            }),
            'primary_email': forms.EmailInput(),
            'website_url': forms.URLInput(),
            'logo_url': forms.URLInput(),
            'notes': forms.Textarea(attrs={
                'rows': 4
            }),
            'prime': forms.TextInput(attrs={
                'class': 'w-10'  # Keep this specific width class
            }),
            # Boolean fields as checkboxes for toggle switches
            'probation': forms.CheckboxInput(),
            'conditional': forms.CheckboxInput(),
            'ppi': forms.CheckboxInput(),
            'iso': forms.CheckboxInput(),
            'is_packhouse': forms.CheckboxInput(),
            'archived': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sort select field choices
        if 'packhouse' in self.fields:
            self.fields['packhouse'].queryset = self.fields['packhouse'].queryset.order_by('name')
        if 'contact' in self.fields:
            self.fields['contact'].queryset = self.fields['contact'].queryset.order_by('name')
        
        # Handle null boolean fields - treat None as False for display
        if self.instance and self.instance.pk:
            for field_name in ['probation', 'conditional', 'ppi', 'iso', 'is_packhouse', 'archived']:
                if field_name in self.fields:
                    value = getattr(self.instance, field_name, None)
                    if value is None:
                        self.initial[field_name] = False

class ContractForm(BaseModelForm):
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
            'idiq_contract', 'contract_number', 'status', 'date_closed',
            'date_canceled', 'canceled_reason', 'po_number', 'tab_num',
            'buyer', 'contract_type', 'award_date', 'due_date', 'due_date_late',
            'sales_class', 'survey_date', 'survey_type', 'assigned_user',
            'assigned_date', 'nist', 'files_url', 'reviewed', 'reviewed_by',
            'reviewed_on', 'contract_value', 'plan_gross', 'solicitation_type',
            'prime', 'prime_po_number'
        ]
        widgets = {
            # Only specify widgets that need special attributes
            'date_closed': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'date_canceled': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'award_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'due_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'survey_date': forms.DateInput(attrs={
                'type': 'date'
            }),
            'assigned_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'reviewed_on': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'contract_value': forms.NumberInput(attrs={
                'step': '0.01'
            }),
            'plan_gross': forms.NumberInput(attrs={
                'step': '0.01'
            })
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

class ContractCloseForm(BaseModelForm):
    class Meta:
        model = Contract
        fields = ['status', 'date_closed']
        widgets = {
            'date_closed': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            })
        }


class SupplierTypeForm(BaseModelForm):
    class Meta:
        model = SupplierType
        fields = ['code', 'description']


class CertificationTypeForm(BaseModelForm):
    class Meta:
        model = CertificationType
        fields = ['code', 'name']


class ClassificationTypeForm(BaseModelForm):
    class Meta:
        model = ClassificationType
        fields = ['name']


class CompanyForm(BaseModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('username'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Select the users who should have access to this company.'
    )

    class Meta:
        model = Company
        fields = ['name', 'is_active', 'logo', 'primary_color', 'secondary_color']
        widgets = {
            'logo': forms.ClearableFileInput(attrs={
                'class': 'form-input'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Style the color inputs
        if 'primary_color' in self.fields:
            self.fields['primary_color'].widget.attrs.update({
                'type': 'color',
                'class': 'h-10 w-20 rounded border border-gray-300 cursor-pointer'
            })
        if 'secondary_color' in self.fields:
            self.fields['secondary_color'].widget.attrs.update({
                'type': 'color',
                'class': 'h-10 w-20 rounded border border-gray-300 cursor-pointer'
            })

        # Members field initial data
        if 'members' in self.fields:
            self.fields['members'].widget.attrs.setdefault('class', 'space-y-2')
            if self.instance.pk:
                self.fields['members'].initial = list(
                    self.instance.user_memberships.values_list('user_id', flat=True)
                )
            else:
                self.fields['members'].initial = []

        self._pending_members = None

    def clean_logo(self):
        file = self.cleaned_data.get('logo')
        if not file:
            return file

        # Validate content type
        content_type = getattr(file, 'content_type', None)
        allowed_types = {
            'image/png', 'image/jpeg', 'image/jpg', 'image/svg+xml'
        }
        if content_type and content_type.lower() not in allowed_types:
            raise forms.ValidationError('Unsupported file type. Please upload PNG, JPEG, or SVG.')

        # Validate file extension as a fallback if content_type missing
        name = getattr(file, 'name', '')
        if name and not name.lower().endswith(('.png', '.jpg', '.jpeg', '.svg')):
            raise forms.ValidationError('Unsupported file type. Please upload PNG, JPEG, or SVG.')

        # Optional: validate dimensions for raster images if Pillow is available
        if content_type and content_type.lower() in {'image/png', 'image/jpeg', 'image/jpg'}:
            try:
                from PIL import Image
                file.seek(0)
                img = Image.open(file)
                width, height = img.size
                # Basic sanity caps (too small or too large)
                if width < 64 or height < 32:
                    raise forms.ValidationError('Logo is too small. Minimum size is 64x32.')
                if width > 4096 or height > 4096:
                    raise forms.ValidationError('Logo is too large. Maximum size is 4096x4096.')
                file.seek(0)
            except ImportError:
                # Pillow not installed; skip dimension validation gracefully
                pass
            except Exception:
                # If Pillow fails to read, reject as invalid image
                raise forms.ValidationError('Invalid image file.')

        # Optional: file size limit (e.g., 2 MB)
        if hasattr(file, 'size') and file.size > 2 * 1024 * 1024:
            raise forms.ValidationError('Logo file is too large (max 2 MB).')

        return file

    def _clean_hex(self, value, field_label):
        if value:
            v = value.strip()
            import re
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                raise forms.ValidationError(f'{field_label} must be a hex color like #004eb3.')
            return v
        return value

    def clean_primary_color(self):
        return self._clean_hex(self.cleaned_data.get('primary_color'), 'Primary color')

    def clean_secondary_color(self):
        return self._clean_hex(self.cleaned_data.get('secondary_color'), 'Secondary color')

    def save(self, commit=True):
        company = super().save(commit=commit)
        self._pending_members = self.cleaned_data.get('members', [])
        if commit:
            self._sync_memberships()
        return company

    def save_m2m(self):
        self._sync_memberships()

    def _sync_memberships(self):
        if not hasattr(self, '_pending_members'):
            return

        company = self.instance
        if not company.pk:
            return

        members = self._pending_members
        if members is None:
            members = []

        if hasattr(members, 'values_list'):
            selected_ids = {int(pk) for pk in members.values_list('id', flat=True)}
        else:
            selected_ids = {int(pk) for pk in members}

        current_memberships = UserCompanyMembership.objects.filter(company=company)
        current_ids = {int(pk) for pk in current_memberships.values_list('user_id', flat=True)}

        # Remove memberships that are no longer selected
        for user_id in current_ids - selected_ids:
            UserCompanyMembership.objects.filter(company=company, user_id=user_id).delete()
            remaining = UserCompanyMembership.objects.filter(user_id=user_id)
            if remaining.exists() and not remaining.filter(is_default=True).exists():
                first = remaining.first()
                first.is_default = True
                first.save(update_fields=['is_default'])

        # Add or ensure memberships for selected users
        for user_id in selected_ids:
            membership, created = UserCompanyMembership.objects.get_or_create(company=company, user_id=user_id)
            if created and not UserCompanyMembership.objects.filter(user_id=user_id, is_default=True).exclude(pk=membership.pk).exists():
                membership.is_default = True
                membership.save(update_fields=['is_default'])

        self._pending_members = None

class ContractCancelForm(BaseModelForm):
    class Meta:
        model = Contract
        fields = ['status', 'date_canceled', 'canceled_reason']
        widgets = {
            'date_canceled': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            })
        }

class ClinForm(BaseModelForm):
    class Meta:
        model = Clin
        fields = [
            'contract', 'po_num_ext', 'tab_num', 
            'clin_po_num', 'po_number', 'supplier', 
            'nsn', 'ia', 'fob', 'order_qty', 'ship_qty', 
            'due_date', 'supplier_due_date', 'ship_date',
            'special_payment_terms', 'special_payment_terms_paid', 
            'quote_value', 'paid_amount','unit_price', 'price_per_unit',
            'paid_date', 'wawf_payment', 'wawf_recieved', 
            'wawf_invoice', 'item_number', 'item_type', 'item_value'
        ]
        widgets = {
            # Only specify widgets that need special attributes
            'due_date': forms.DateInput(attrs={
                'type': 'date'
            }),
            'supplier_due_date': forms.DateInput(attrs={
                'type': 'date'
            }),
            'ship_date': forms.DateInput(attrs={
                'type': 'date'
            }),
            'paid_amount': forms.NumberInput(attrs={
                'step': '0.01',
                'readonly': True
            }),
            'paid_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'wawf_payment': forms.NumberInput(attrs={
                'step': '0.01',
                'readonly': True
            }),
            'wawf_recieved': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'quote_value': forms.NumberInput(attrs={
                'step': '0.01'
            }),
            'unit_price': forms.NumberInput(attrs={
                'step': '0.01'
            }),
            'price_per_unit': forms.NumberInput(attrs={
                'step': '0.01'
            }),
            'item_value': forms.NumberInput(attrs={
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
            self.fields['item_type'].choices = self._meta.model.ITEM_TYPE_CHOICES
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
            
            # Load all Item types
            self.fields['item_type'].choices = self._meta.model.ITEM_TYPE_CHOICES
            
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

class NoteForm(BaseModelForm):
    class Meta:
        model = Note
        fields = ['note']
        widgets = {
            'note': forms.Textarea(attrs={
                'rows': 4
            })
        }

class ReminderForm(BaseModelForm):
    assigned_to = ActiveUserModelChoiceField(
        required=False,
        empty_label="Select User",
    )
    
    class Meta:
        model = Reminder
        fields = ['reminder_title', 'reminder_text', 'reminder_date', 'reminder_user', 'reminder_completed']
        widgets = {
            'reminder_text': forms.Textarea(attrs={
                'rows': 3
            }),
            'reminder_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            })
        }

class ClinAcknowledgmentForm(BaseModelForm):
    class Meta:
        model = ClinAcknowledgment
        fields = [
            'po_to_supplier_bool', 'po_to_supplier_date',
            'clin_reply_bool', 'clin_reply_date',
            'po_to_qar_bool', 'po_to_qar_date'
        ]
        widgets = {
            'po_to_supplier_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'clin_reply_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            }),
            'po_to_qar_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local'
            })
        }

class AcknowledgementLetterForm(BaseModelForm):
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
                'type': 'date'
            }),
            'fat_plt_due_date': forms.DateInput(attrs={
                'type': 'date'
            }),
            'supplier_due_date': forms.DateInput(attrs={
                'type': 'date'
            })
        }

class AddressForm(BaseModelForm):
    class Meta:
        model = Address
        fields = ['address_line_1', 'address_line_2', 'city', 'state', 'zip']

class ContactForm(BaseModelForm):
    class Meta:
        model = Contact
        fields = ['salutation', 'name', 'company', 'title', 'phone', 'email', 'address', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={
                'rows': 3
            })
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

class IdiqContractForm(BaseModelForm):
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
            'contract_number': forms.TextInput(),
            'buyer': forms.Select(),
            'award_date': forms.DateInput(attrs={
                'type': 'date'
            }),
            'term_length': forms.NumberInput(attrs={
                'min': 0
            }),
            'option_length': forms.NumberInput(attrs={
                'min': 0
            }),
            'closed': forms.Select(),
            'tab_num': forms.TextInput()
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Convert award_date to date-only format if it exists
        if self.instance and self.instance.award_date:
            self.initial['award_date'] = self.instance.award_date.date()

class IdiqContractDetailsForm(forms.ModelForm):
    class Meta:
        model = IdiqContractDetails
        fields = ['nsn', 'supplier']
        widgets = {
            'nsn': forms.Select(attrs={'class': 'select2'}),
            'supplier': forms.Select(attrs={'class': 'select2'}),
        }


class ContractTypeForm(BaseModelForm):
    class Meta:
        model = ContractType
        fields = ['description']


class SalesClassForm(BaseModelForm):
    class Meta:
        model = SalesClass
        fields = ['sales_team']


class SpecialPaymentTermsForm(BaseModelForm):
    class Meta:
        model = SpecialPaymentTerms
        fields = ['code', 'terms']


class ClinTypeForm(BaseModelForm):
    class Meta:
        model = ClinType
        fields = ['description', 'raw_text']
