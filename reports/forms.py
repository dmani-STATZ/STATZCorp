from django import forms
from .models import ReportRequest


class ReportRequestForm(forms.ModelForm):
    class Meta:
        model = ReportRequest
        fields = ["title", "description", "category"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class SQLUpdateForm(forms.ModelForm):
    class Meta:
        model = ReportRequest
        fields = ["sql_query", "context_notes"]
        widgets = {
            "sql_query": forms.Textarea(attrs={"rows": 10, "spellcheck": "false"}),
            "context_notes": forms.Textarea(attrs={"rows": 4}),
        }

