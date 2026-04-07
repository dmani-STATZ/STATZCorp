"""
Sales app forms.
"""
from django import forms

from contracts.models import Company
from sales.models import CompanyCAGE


_SB_REPRESENTATIONS_CHOICES = [
    ("Y", "Y - Small Business Set-Aside"),
    ("H", "H - HUBZone Set-Aside"),
    ("R", "R - Service Disabled Veteran-Owned Small Business (SDVOSB)"),
    ("L", "L - Woman-Owned Small Business (WOSB) Set-Aside"),
    ("A", "A - 8(a) Set-Aside"),
    ("E", "E - Economically Disadvantaged Woman-Owned (EDWOSB)"),
    ("N", "N - Unrestricted/Not Set-Aside"),
]

_AFFIRMATIVE_CHOICES = [
    ("Y6", "Y6 — Developed and on File"),
    ("N6", "N6 — Not Developed and Not on File"),
    ("NH", "NH — No Previous Contracts Subject to Requirements"),
    ("NA", "NA — Not Applicable"),
]

_PREV_CONTRACTS_CHOICES = [
    ("Y4", "Y4 — Participated and Filed"),
    ("Y5", "Y5 — Participated and Not Filed"),
    ("N4", "N4 — Not Participated"),
    ("NA", "NA — Not Applicable"),
]

_ADR_CHOICES = [
    ("A", "A — Agree To Use Alternate Disputes Resolution"),
    ("B", "B — Do Not Agree To Use Alternate Disputes Resolution"),
]

_FIELD_STYLE = (
    "width:100%; padding:0.5rem 0.75rem; border:1px solid #d1d5db; "
    "border-radius:6px; font-size:0.875rem;"
)
_MONO_STYLE = _FIELD_STYLE + " font-family:monospace; text-transform:uppercase;"


class CompanyCAGEForm(forms.ModelForm):
    """CAGE settings for BQ export and award queue injection (linked contracts company)."""

    class Meta:
        model = CompanyCAGE
        fields = [
            "cage_code",
            "company_name",
            "company",
            "smtp_reply_to",
            "default_markup_pct",
            "sb_representations_code",
            "affirmative_action_code",
            "previous_contracts_code",
            "alternate_disputes_resolution",
            "default_fob_point",
            "default_payment_terms",
            "default_child_labor_code",
            "is_default",
            "is_active",
        ]
        widgets = {
            "default_fob_point": forms.HiddenInput(),
            "default_payment_terms": forms.HiddenInput(),
            "default_child_labor_code": forms.HiddenInput(),
            "is_default": forms.CheckboxInput(
                attrs={"style": "width:15px; height:15px; cursor:pointer;"}
            ),
            "is_active": forms.CheckboxInput(
                attrs={"style": "width:15px; height:15px; cursor:pointer;"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["company"].empty_label = "--- Select Company ---"
        self.fields["company"].required = False
        self.fields["company_name"].required = False

        self.fields["sb_representations_code"].widget = forms.Select(
            choices=_SB_REPRESENTATIONS_CHOICES,
            attrs={"style": _FIELD_STYLE},
        )
        self.fields["affirmative_action_code"].widget = forms.Select(
            choices=_AFFIRMATIVE_CHOICES,
            attrs={"style": _FIELD_STYLE},
        )
        self.fields["previous_contracts_code"].widget = forms.Select(
            choices=_PREV_CONTRACTS_CHOICES,
            attrs={"style": _FIELD_STYLE},
        )
        self.fields["alternate_disputes_resolution"].widget = forms.Select(
            choices=_ADR_CHOICES,
            attrs={"style": _FIELD_STYLE},
        )

        self.fields["cage_code"].widget.attrs.update(
            {"maxlength": 5, "style": _MONO_STYLE, "required": True}
        )
        self.fields["company_name"].widget.attrs.update({"style": _FIELD_STYLE, "maxlength": 150})
        self.fields["smtp_reply_to"].widget.attrs.update(
            {
                "style": _FIELD_STYLE,
                "placeholder": "bids@company.com",
            }
        )
        self.fields["default_markup_pct"].widget.attrs.update(
            {"style": _FIELD_STYLE, "step": "0.01", "min": "0", "max": "100"}
        )
        self.fields["company"].widget.attrs.update({"style": _FIELD_STYLE})

    def clean_cage_code(self):
        return (self.cleaned_data.get("cage_code") or "").strip().upper()


class ImportUploadForm(forms.Form):
    """Three-file upload for daily DIBBS import (IN, BQ, AS)."""
    in_file = forms.FileField(label='IN File')
    bq_file = forms.FileField(label='BQ File')
    as_file = forms.FileField(label='AS File')


class AwardUploadForm(forms.Form):
    aw_file = forms.FileField(
        label="AW File",
        help_text="Upload the AW file from the Office File Portal. Filename must be aw[YYMMDD].txt",
    )
