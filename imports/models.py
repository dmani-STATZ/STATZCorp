from django.db import models
from django.contrib.auth.models import User


class ImportSession(models.Model):

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('previewing', 'Previewing'),
        ('committed', 'Committed'),
    ]

    uploaded_filename = models.CharField(max_length=255)
    target_model = models.CharField(max_length=100)
    # Value must be a key from imports/config.py IMPORT_TARGETS
    # e.g. 'suppliers.Supplier'

    match_field = models.CharField(max_length=100)
    # The field on the target model used to fuzzy-match rows
    # User selects this at session setup time

    column_map = models.JSONField(default=dict)
    # Maps spreadsheet column headers to target model field names
    # e.g. {"Vendor": "name", "Terms": "special_terms_id"}

    matched_count = models.IntegerField(default=0)
    unmatched_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    committed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.target_model} import — {self.uploaded_filename} ({self.status})"


class ImportRow(models.Model):

    STATUS_CHOICES = [
        ('matched', 'Matched'),
        ('unmatched', 'Unmatched'),
        ('skipped', 'Skipped'),
        ('committed', 'Committed'),
    ]

    session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name='rows')
    row_number = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unmatched')
    match_confidence = models.FloatField(null=True, blank=True)
    # Token-sort SequenceMatcher ratio, 0.0–1.0

    raw_data = models.JSONField(default=dict)
    # The original spreadsheet row as-is
    # e.g. {"Vendor": "AAA Air Support", "Terms": "NET 30"}

    proposed_changes = models.JSONField(default=dict)
    # Field:value pairs to write to the target model on commit
    # e.g. {"special_terms_id": 4}

    matched_target_id = models.IntegerField(null=True, blank=True)
    # The pk of the matched record in the target model table.
    # NOT a real FK — the actual model is implied by session.target_model.
    # Reconstructed at commit time using target_model + matched_target_id together.

    class Meta:
        ordering = ['row_number']

    def __str__(self):
        return f"Row {self.row_number} — {self.status} (session {self.session_id})"


class ValueTranslationMap(models.Model):
    """
    Reusable lookup table mapping raw spreadsheet values to FK integer IDs.
    Scoped per target_model + target_field combination.
    Auto-populated when a user manually resolves an FK mapping during preview.
    Grows smarter with each import session.
    """

    target_model = models.CharField(max_length=100)
    # e.g. 'suppliers.Supplier'

    target_field = models.CharField(max_length=100)
    # e.g. 'special_terms_id'

    raw_value = models.CharField(max_length=255)
    # e.g. 'NET 30'

    resolved_id = models.IntegerField()
    # e.g. 4

    class Meta:
        unique_together = [('target_model', 'target_field', 'raw_value')]
        ordering = ['target_model', 'target_field', 'raw_value']

    def __str__(self):
        return f"{self.target_model}.{self.target_field}: '{self.raw_value}' → {self.resolved_id}"
