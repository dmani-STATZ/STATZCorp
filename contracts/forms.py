from django import forms
from .models import Nsn, Supplier

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