from django import forms
from django.contrib.auth import get_user_model

from .models import ReportDraft, ReportRequest, ReportShare, ReportVersion

User = get_user_model()


class ReportRequestForm(forms.ModelForm):
    class Meta:
        model = ReportRequest
        fields = ["description"]
        labels = {
            "description": "Describe the report you need",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class ReportRequestChangeForm(forms.ModelForm):
    class Meta:
        model = ReportRequest
        fields = ["description", "keep_original"]
        labels = {
            "keep_original": "Keep original report unchanged (creates a branch)",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "keep_original": forms.CheckboxInput(),
        }


class AdminReportRequestForm(forms.ModelForm):
    class Meta:
        model = ReportRequest
        fields = ["admin_notes", "status"]
        widgets = {
            "admin_notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (ReportRequest.STATUS_IN_PROGRESS, "In Progress"),
            (ReportRequest.STATUS_COMPLETED, "Completed"),
            (ReportRequest.STATUS_CHANGE_REQUESTED, "Change Requested"),
        ]


class ReportVersionForm(forms.ModelForm):
    class Meta:
        model = ReportVersion
        fields = ["sql_query", "context_notes", "change_notes"]
        widgets = {
            "sql_query": forms.Textarea(attrs={"rows": 12, "spellcheck": "false"}),
            "context_notes": forms.Textarea(attrs={"rows": 3}),
            "change_notes": forms.Textarea(attrs={"rows": 2}),
        }


class ReportShareForm(forms.ModelForm):
    shared_with = forms.ModelChoiceField(queryset=User.objects.none())

    class Meta:
        model = ReportShare
        fields = ["shared_with", "can_branch"]
        labels = {
            "can_branch": "Allow recipient to branch this report",
        }


class ReportDraftPromptForm(forms.ModelForm):
    class Meta:
        model = ReportDraft
        fields = ["original_prompt"]
        labels = {
            "original_prompt": "Describe the report you want",
        }
        widgets = {
            "original_prompt": forms.Textarea(attrs={"rows": 5}),
        }


class ReportDraftFeedbackForm(forms.ModelForm):
    class Meta:
        model = ReportDraft
        fields = ["latest_feedback"]
        labels = {
            "latest_feedback": "What needs to change?",
        }
        widgets = {
            "latest_feedback": forms.Textarea(attrs={"rows": 3}),
        }

