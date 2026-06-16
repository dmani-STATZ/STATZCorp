from django import forms
from .models import Campaign, CampaignRecipient, CampaignFollowUp
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe
import csv
import io

MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024  # 5MB

class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ['name', 'sender_email', 'subject_template', 'body_template', 'is_html_body']
        widgets = {
            'subject_template': forms.TextInput(attrs={'placeholder': 'Hello {first_name}'}),
            'body_template': forms.HiddenInput(),  # Quill manages this via JS
            'is_html_body': forms.HiddenInput(),    # Set by JS based on editor mode
        }
        help_texts = {
            'subject_template': 'You can use variables like {first_name}, {last_name}, {company_name}.',
        }

class CampaignAttachmentForm(forms.Form):
    file = forms.FileField(
        help_text="Max 5MB per file. Accepted: PDF, images, Word, Excel."
    )

    ALLOWED_CONTENT_TYPES = [
        'application/pdf',
        'image/png', 'image/jpeg', 'image/gif', 'image/webp',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/csv',
    ]

    def clean_file(self):
        uploaded = self.cleaned_data['file']
        if uploaded.size > MAX_ATTACHMENT_SIZE:
            raise ValidationError(
                f"File is too large ({uploaded.size / (1024*1024):.1f} MB). Maximum allowed is 5 MB."
            )
        return uploaded

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

class CampaignAIGenerateForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ['ai_instruction']
        widgets = {
            'ai_instruction': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': 'e.g. Write a friendly sentence to win them back based on their drop off. Keep it under 2 sentences.'
            }),
        }
        labels = {
            'ai_instruction': 'Instruction for Claude'
        }
        help_texts = {
            'ai_instruction': 'The AI will receive this instruction along with each recipient\'s custom data and generate a unique message for them.'
        }

class CampaignFollowUpForm(forms.ModelForm):
    class Meta:
        model = CampaignFollowUp
        fields = ['delay_days', 'subject_template', 'body_template']
        widgets = {
            'delay_days': forms.NumberInput(attrs={'min': 1}),
            'body_template': forms.HiddenInput(),  # Quill manages this via JS
        }
