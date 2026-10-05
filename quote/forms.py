import re

from django import forms
from django.core.exceptions import ValidationError

_CAGE_RE = re.compile(r'^[A-Z0-9]{5}$')


class CageLookupForm(forms.Form):
    cage = forms.CharField(
        max_length=5,
        min_length=5,
        required=True,
        label='CAGE Code',
        widget=forms.TextInput(attrs={
            'autofocus': True,
            'autocomplete': 'off',
            'maxlength': 5,
            'class': 'form-control text-uppercase fs-5',
        }),
    )

    def clean_cage(self):
        value = self.cleaned_data['cage'].strip().upper()
        if not _CAGE_RE.match(value):
            raise ValidationError('CAGE must be exactly 5 letters or digits.')
        return value
