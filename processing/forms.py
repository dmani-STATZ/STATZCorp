from django import forms
from django.forms import inlineformset_factory
from .models import ProcessContract, ProcessClin

class ProcessContractForm(forms.ModelForm):
    class Meta:
        model = ProcessContract
        fields = [
            'idiq_contract',
            'contract_number',
            'solicitation_type',
            'po_number',
            'tab_num',
            'buyer',
            'buyer_text',
            'contract_type',
            'award_date',
            'due_date',
            'due_date_late',
            'sales_class',
            'nist',
            'files_url',
            'contract_value',
            'description',
            'planned_split',
            'ppi_split',
            'statz_split',
            'ppi_split_paid',
            'statz_split_paid',
            'status'
        ]
        widgets = {
            'award_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'buyer_text': forms.TextInput(attrs={'class': 'buyer-text-input'}),
            'files_url': forms.URLInput(attrs={'class': 'url-input'}),
            'planned_split': forms.TextInput(attrs={'class': 'split-input'}),
            'ppi_split': forms.NumberInput(attrs={'step': '0.0001', 'class': 'split-input'}),
            'statz_split': forms.NumberInput(attrs={'step': '0.0001', 'class': 'split-input'}),
            'ppi_split_paid': forms.NumberInput(attrs={'step': '0.0001', 'class': 'split-input'}),
            'statz_split_paid': forms.NumberInput(attrs={'step': '0.0001', 'class': 'split-input'}),
            'due_date_late': forms.CheckboxInput(attrs={'class': 'checkbox-input'})
        }

class ProcessClinForm(forms.ModelForm):
    class Meta:
        model = ProcessClin
        fields = [
            'item_number',
            'item_type',
            'nsn',
            'nsn_text',
            'nsn_description_text',
            'supplier',
            'supplier_text',
            'order_qty',
            'unit_price',
            'item_value',
            'description',
            'ia',
            'fob',
            'po_num_ext',
            'tab_num',
            'clin_po_num',
            'po_number',
            'clin_type',
            'status'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'nsn_text': forms.TextInput(attrs={'class': 'nsn-text-input'}),
            'nsn_description_text': forms.TextInput(attrs={'class': 'nsn-desc-input'}),
            'supplier_text': forms.TextInput(attrs={'class': 'supplier-text-input'}),
            'order_qty': forms.NumberInput(attrs={'step': '1', 'class': 'qty-input'}),
            'unit_price': forms.NumberInput(attrs={'step': '0.0001', 'class': 'price-input'}),
            'item_value': forms.NumberInput(attrs={'step': '0.0001', 'class': 'value-input', 'readonly': True}),
        }

    def clean(self):
        cleaned_data = super().clean()
        order_qty = cleaned_data.get('order_qty')
        unit_price = cleaned_data.get('unit_price')
        
        if order_qty and unit_price:
            cleaned_data['item_value'] = order_qty * unit_price
        
        return cleaned_data

ProcessClinFormSet = inlineformset_factory(
    ProcessContract,
    ProcessClin,
    form=ProcessClinForm,
    extra=1,
    can_delete=True
) 