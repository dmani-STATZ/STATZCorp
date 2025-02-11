from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, ButtonHolder, Submit
from .models import InventoryItem
from crispy_forms.layout import Column


class InventoryItemForm(forms.ModelForm):
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
                Column('nsn', css_class='form-control', placeholder='NSN'),
                Column('description', css_class='form-control', placeholder='Description'),
                Column('partnumber', css_class='form-control', placeholder='Part Number'),
                Column('manufacturer', css_class='form-control', placeholder='Manufacturer'),
                Column('itemlocation', css_class='form-control', placeholder='Item Location'),
                Column('quantity', css_class='form-control', placeholder='Quantity'),
                Column('purchaseprice', css_class='form-control', placeholder='Purchase Price'),
            ),
            ButtonHolder(
                Submit('submit', 'Add Item', css_class='bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded')
            )
        )
        self.fields['nsn'].widget.attrs.update({'class': 'autocomplete-nsn'})
        self.fields['description'].widget.attrs.update({'class': 'autocomplete-description'})
        self.fields['manufacturer'].widget.attrs.update({'class': 'autocomplete-manufacturer'})
