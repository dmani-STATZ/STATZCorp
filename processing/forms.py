from django import forms
from django.forms import inlineformset_factory
from .models import ProcessContract, ProcessClin, ContractSplit

class ContractSplitForm(forms.ModelForm):
    class Meta:
        model = ContractSplit
        fields = ['company_name', 'split_value', 'split_paid']

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
            'status'
        ]
        widgets = {
            'award_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'buyer_text': forms.TextInput(attrs={'class': 'buyer-text-input'}),
            'files_url': forms.URLInput(attrs={'class': 'url-input'}),
            'due_date_late': forms.CheckboxInput(attrs={'class': 'checkbox-input'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.splits_data = []
        
        if self.data:
            # Extract splits data from POST
            for key in self.data:
                if key.startswith('splits-'):
                    parts = key.split('-')
                    if len(parts) == 3:  # splits-[id/new]-[field]
                        split_id = parts[1]
                        field = parts[2]
                        
                        # Find or create split data dict
                        split_data = next((s for s in self.splits_data if s['id'] == split_id), None)
                        if not split_data:
                            split_data = {'id': split_id}
                            self.splits_data.append(split_data)
                        
                        # Add field value
                        split_data[field] = self.data[key]

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        if commit:
            instance.save()
            
            # Handle splits
            if self.splits_data:
                # Delete removed splits
                existing_split_ids = [s['id'] for s in self.splits_data if not s['id'].startswith('new')]
                instance.splits.exclude(id__in=existing_split_ids).delete()
                
                # Update/create splits
                for split_data in self.splits_data:
                    split_id = split_data['id']
                    
                    if split_id.startswith('new'):
                        # Create new split
                        ContractSplit.objects.create(
                            process_contract=instance,
                            company_name=split_data['company'],
                            split_value=split_data.get('value') or 0,
                            split_paid=split_data.get('paid') or 0
                        )
                    else:
                        # Update existing split
                        split = instance.splits.get(id=split_id)
                        split.company_name = split_data['company']
                        split.split_value = split_data.get('value') or 0
                        split.split_paid = split_data.get('paid') or 0
                        split.save()
        
        return instance

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
    fields=('item_number', 'item_type', 'nsn', 'supplier', 'order_qty', 'unit_price', 'item_value', 'status'),
    extra=0,
    can_delete=True
) 