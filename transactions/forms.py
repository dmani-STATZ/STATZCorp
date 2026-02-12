"""
Transaction form for the modal: supports all field types (date, select, text, number, boolean).
Widget type is determined from the model field via field_types.get_field_info().
"""
from django import forms
from .models import Transaction
from .field_types import get_field_info, WIDGET_DATE, WIDGET_DATETIME, WIDGET_BOOLEAN, WIDGET_SELECT, WIDGET_NUMBER


def _input_attrs(editable=True):
    base = {
        "class": "form-input block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100",
    }
    if not editable:
        base["readonly"] = True
    return base


class TransactionForm(forms.ModelForm):
    """Form for viewing one transaction in the modal. Old/new value widgets are set in __init__ from field_info."""

    class Meta:
        model = Transaction
        fields = ("field_name", "old_value", "new_value")
        widgets = {
            "field_name": forms.TextInput(attrs={"class": "form-input block w-full rounded-md border-gray-300 dark:bg-gray-700 dark:border-gray-600", "readonly": True}),
        }

    def __init__(self, content_type_id=None, field_name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._field_info = None
        if content_type_id and field_name:
            self._field_info = get_field_info(content_type_id, field_name)
            if self._field_info:
                self._set_value_widgets()

    def _set_value_widgets(self):
        info = self._field_info
        wt = info["widget_type"]
        attrs = {**_input_attrs(editable=False)}

        if wt == WIDGET_DATE:
            self.fields["old_value"].widget = forms.DateInput(attrs={**attrs, "type": "date"})
            self.fields["new_value"].widget = forms.DateInput(attrs={**attrs, "type": "date"})
        elif wt == WIDGET_DATETIME:
            self.fields["old_value"].widget = forms.DateTimeInput(attrs={**attrs, "type": "datetime-local"})
            self.fields["new_value"].widget = forms.DateTimeInput(attrs={**attrs, "type": "datetime-local"})
        elif wt == WIDGET_BOOLEAN:
            self.fields["old_value"].widget = forms.Select(choices=info.get("choices") or [], attrs=attrs)
            self.fields["new_value"].widget = forms.Select(choices=info.get("choices") or [], attrs=attrs)
        elif wt == WIDGET_SELECT:
            choices = info.get("choices") or []
            self.fields["old_value"].widget = forms.Select(choices=choices, attrs=attrs)
            self.fields["new_value"].widget = forms.Select(choices=choices, attrs=attrs)
        elif wt == WIDGET_NUMBER:
            self.fields["old_value"].widget = forms.NumberInput(attrs=attrs)
            self.fields["new_value"].widget = forms.NumberInput(attrs=attrs)
        else:
            self.fields["old_value"].widget = forms.Textarea(attrs={**attrs, "rows": 2})
            self.fields["new_value"].widget = forms.Textarea(attrs={**attrs, "rows": 2})

    @property
    def field_info(self):
        return self._field_info


class EditFieldForm(forms.Form):
    """Single field 'new_value' for editing a model field in the modal. Widget set from field_info."""

    new_value = forms.CharField(required=False, label="New value")

    def __init__(self, content_type_id=None, field_name=None, initial_value=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._field_info = get_field_info(content_type_id, field_name) if (content_type_id and field_name) else None
        self._content_type_id = content_type_id
        self._field_name = field_name
        if initial_value is not None:
            self.fields["new_value"].initial = initial_value
        if self._field_info:
            self._set_widget()

    def _set_widget(self):
        info = self._field_info
        wt = info["widget_type"]
        attrs = _input_attrs(editable=True)
        choices = info.get("choices")

        if wt == WIDGET_DATE:
            self.fields["new_value"].widget = forms.DateInput(attrs={**attrs, "type": "date"})
        elif wt == WIDGET_DATETIME:
            self.fields["new_value"].widget = forms.DateTimeInput(attrs={**attrs, "type": "datetime-local"})
        elif wt == WIDGET_BOOLEAN:
            self.fields["new_value"].widget = forms.Select(choices=choices or [], attrs=attrs)
        elif wt == WIDGET_SELECT:
            self.fields["new_value"].widget = forms.Select(choices=choices or [], attrs=attrs)
        elif wt == WIDGET_NUMBER:
            self.fields["new_value"].widget = forms.NumberInput(attrs=attrs)
        else:
            self.fields["new_value"].widget = forms.Textarea(attrs={**attrs, "rows": 2})

    @property
    def field_info(self):
        return self._field_info
