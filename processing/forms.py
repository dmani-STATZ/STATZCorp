from django import forms
from django.forms import inlineformset_factory
from .models import ProcessContract, ProcessCLIN

class ProcessContractForm(forms.ModelForm):
    class Meta:
        model = ProcessContract
        fields = [
            'contract_number',
            'buyer',
            'award_date',
            'due_date',
            'contract_value',
            'description',
            'status'
        ]
        widgets = {
            'award_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

class ProcessCLINForm(forms.ModelForm):
    class Meta:
        model = ProcessCLIN
        fields = [
            'clin_number',
            'nsn',
            'supplier',
            'quantity',
            'unit_price',
            'total_price',
            'description',
            'status'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def clean(self):
        cleaned_data = super().clean()
        quantity = cleaned_data.get('quantity')
        unit_price = cleaned_data.get('unit_price')
        
        if quantity and unit_price:
            cleaned_data['total_price'] = quantity * unit_price
        
        return cleaned_data

ProcessCLINFormSet = inlineformset_factory(
    ProcessContract,
    ProcessCLIN,
    form=ProcessCLINForm,
    extra=0,
    can_delete=True
) 