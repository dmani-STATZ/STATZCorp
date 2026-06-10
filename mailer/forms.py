from django import forms
from .models import Campaign
from django.core.exceptions import ValidationError
import csv
import io

class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ['name', 'sender_email', 'subject_template', 'body_template']
        widgets = {
            'body_template': forms.Textarea(attrs={'rows': 10}),
        }

class CampaignRecipientImportForm(forms.Form):
    csv_file = forms.FileField(
        required=False, 
        help_text="Upload a CSV file containing columns: email, first_name, last_name, company_name"
    )
    email_text = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 5, 'placeholder': 'john@example.com; jane@example.com'}),
        required=False,
        help_text="Or paste a semicolon-separated list of email addresses"
    )

    def clean(self):
        cleaned_data = super().clean()
        csv_file = cleaned_data.get('csv_file')
        email_text = cleaned_data.get('email_text')

        if not csv_file and not email_text:
            raise ValidationError("You must provide either a CSV file or paste email addresses.")
        
        return cleaned_data
