"""
Sales app forms.
"""
from django import forms


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
