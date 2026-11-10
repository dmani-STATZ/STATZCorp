from django import forms
from django.core.exceptions import ValidationError

from .models import InventoryItem


class BaseFormMixin:
    """Base form mixin that provides consistent styling for all form widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

    def _style_fields(self):
        """Apply consistent styling to all form fields based on their widget type."""
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.TextInput, forms.NumberInput,
                                   forms.EmailInput, forms.URLInput)):
                widget.attrs['class'] = 'form-input'
            elif isinstance(widget, forms.Select):
                widget.attrs['class'] = 'form-select'
            elif isinstance(widget, forms.Textarea):
                widget.attrs['class'] = 'form-input'
                if 'rows' not in widget.attrs:
                    widget.attrs['rows'] = 3
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = 'form-checkbox'

            if not widget.attrs.get('placeholder') and field.label:
                widget.attrs['placeholder'] = f'Enter {field.label}'


class BaseModelForm(BaseFormMixin, forms.ModelForm):
    """Base ModelForm that implements the form-styling-rule."""
    pass


class InventoryItemForm(BaseModelForm):
    class Meta:
        model = InventoryItem
        exclude = ['id', 'totalcost']
        labels = {
            'nsn': 'NSN',
            'description': 'Description',
            'partnumber': 'Part Number',
            'manufacturer': 'Manufacturer',
            'itemlocation': 'Location',
            'quantity': 'Quantity',
            'quantity_remaining': 'Qty Remaining',
            'purchaseprice': 'Unit Price',
            'is_public': 'Show on public website',
        }
        help_texts = {
            'quantity_remaining': 'For bulk lots drawn down over time. Leave blank if Quantity is the on-hand count.',
        }
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': '0', 'step': '1'}),
            'quantity_remaining': forms.NumberInput(attrs={'min': '0', 'step': '1'}),
            'purchaseprice': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.pop('placeholder', None)
            if name == 'is_public':
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'
        self.fields['nsn'].widget.attrs['class'] += ' autocomplete-nsn'
        self.fields['description'].widget.attrs['class'] += ' autocomplete-description'
        self.fields['manufacturer'].widget.attrs['class'] += ' autocomplete-manufacturer'

    def clean_quantity(self):
        value = self.cleaned_data.get('quantity')
        if value is not None and value < 0:
            raise ValidationError('Quantity cannot be negative.')
        return value

    def clean_quantity_remaining(self):
        value = self.cleaned_data.get('quantity_remaining')
        if value is not None and value < 0:
            raise ValidationError('Qty remaining cannot be negative.')
        return value

    def clean_purchaseprice(self):
        value = self.cleaned_data.get('purchaseprice')
        if value is not None and value < 0:
            raise ValidationError('Unit price cannot be negative.')
        return value
