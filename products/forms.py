from decimal import Decimal

from django import forms

from products.models import Nsn


class NsnLogisticsForm(forms.ModelForm):
    """Bounded logistics edit — the portal's sole write path."""

    class Meta:
        model = Nsn
        fields = (
            'unit_weight',
            'unit_length',
            'unit_width',
            'unit_height',
            'packaging_notes',
        )
        widgets = {
            'unit_weight': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
            }),
            'unit_length': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
            }),
            'unit_width': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
            }),
            'unit_height': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
            }),
            'packaging_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
            }),
        }

    def clean_unit_weight(self):
        return self._clean_decimal('unit_weight')

    def clean_unit_length(self):
        return self._clean_decimal('unit_length')

    def clean_unit_width(self):
        return self._clean_decimal('unit_width')

    def clean_unit_height(self):
        return self._clean_decimal('unit_height')

    def _clean_decimal(self, field_name):
        value = self.cleaned_data.get(field_name)
        if value is None or value == '':
            return None
        if value < 0:
            raise forms.ValidationError('Must be zero or positive.')
        return value
