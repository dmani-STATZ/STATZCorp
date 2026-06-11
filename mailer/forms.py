from django import forms
from .models import Campaign
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe
import csv
import io

class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ['name', 'sender_email', 'subject_template', 'body_template']
        widgets = {
            'subject_template': forms.TextInput(attrs={'placeholder': 'Hello {first_name}'}),
            'body_template': forms.Textarea(attrs={
                'rows': 10,
                'placeholder': 'Dear {first_name},\n\nWe noticed you won {won_2023} contracts in 2023. {ai_custom_message}'
            }),
        }
        help_texts = {
            'subject_template': 'You can use variables like {first_name}, {last_name}, {company_name}.',
            'body_template': mark_safe(
                'Use {first_name}, {last_name}, {company_name} for basic personalization.<br><br>'
                '<strong>Dynamic Audience Variables:</strong> If you built your audience via a database query, '
                'you can directly use the calculated stats (e.g., <code>{won_2023}</code>, <code>{won_2024}</code>).<br><br>'
                '<strong>LLM Personalization:</strong> If you generated AI messages, use <code>{ai_custom_message}</code> '
                'where you want the custom paragraph to appear.'
            ),
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

class AudienceBuilderForm(forms.Form):
    YEAR_CHOICES = [
        ('2022', '2022'),
        ('2023', '2023'),
        ('2024', '2024'),
        ('2025', '2025'),
    ]
    target_years = forms.MultipleChoiceField(
        choices=YEAR_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select the years. Suppliers who won contracts in ANY of these years will be added."
    )
