from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, ButtonHolder, Submit, Column
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
            
            # Add placeholder if not present
            if not widget.attrs.get('placeholder') and field.label:
                widget.attrs['placeholder'] = f'Enter {field.label}'

class BaseModelForm(BaseFormMixin, forms.ModelForm):
    """Base ModelForm that implements the form-styling-rule."""
    pass

class InventoryItemForm(BaseModelForm):
    class Meta:
        model = InventoryItem
        # fields = ['nsn','description', 'partnumber','manufacturer','itemlocation','quantity','purchaseprice']
        exclude = ['id','totalcost']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Fieldset(
                Column('nsn', css_class='form-group'),
                Column('description', css_class='form-group'),
                Column('partnumber', css_class='form-group'),
                Column('manufacturer', css_class='form-group'),
                Column('itemlocation', css_class='form-group'),
                Column('quantity', css_class='form-group'),
                Column('purchaseprice', css_class='form-group'),
            ),
            ButtonHolder(
                Submit('submit', 'Add Item', css_class='btn-primary')
            )
        )
        self.fields['nsn'].widget.attrs.update({'class': 'form-input autocomplete-nsn'})
        self.fields['description'].widget.attrs.update({'class': 'form-input autocomplete-description'})
        self.fields['manufacturer'].widget.attrs.update({'class': 'form-input autocomplete-manufacturer'})
