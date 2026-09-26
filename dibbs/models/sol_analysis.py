from django.db import models


class SolAnalysis(models.Model):
    """
    LLM-extracted bid-critical requirements from a DIBBS solicitation PDF.
    One row per solicitation. Written once; never updated (PDF is static).
    Table: dibbs_sol_analysis
    """

    solicitation = models.OneToOneField(
        "Solicitation",
        on_delete=models.CASCADE,
        related_name="analysis",
        db_column="solicitation_id",
    )

    # --- Metadata ---
    model_key = models.CharField(max_length=20)
    analyzed_at = models.DateTimeField(auto_now_add=True)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)

    # --- Page 1 / SF-18 Cover ---
    issue_date = models.DateField(null=True, blank=True)
    dpas_rating = models.CharField(max_length=10, null=True, blank=True)
    issuing_office = models.CharField(max_length=200, null=True, blank=True)
    buyer_name = models.CharField(max_length=100, null=True, blank=True)
    buyer_email = models.CharField(max_length=100, null=True, blank=True)
    buyer_phone = models.CharField(max_length=50, null=True, blank=True)

    # --- Critical Requirements ---
    fat_required = models.BooleanField(null=True, blank=True)
    fat_units = models.IntegerField(null=True, blank=True)
    fat_days = models.IntegerField(null=True, blank=True)
    fat_summary = models.TextField(null=True, blank=True)
    itar_export_control = models.BooleanField(null=True, blank=True)
    origin_inspection_required = models.BooleanField(null=True, blank=True)
    iso_9001_required = models.BooleanField(null=True, blank=True)
    buy_american_applies = models.BooleanField(null=True, blank=True)
    additive_manufacturing_prohibited = models.BooleanField(null=True, blank=True)
    cmmc_required = models.BooleanField(null=True, blank=True)
    cmmc_level = models.IntegerField(null=True, blank=True)
    quantity_ranges_encouraged = models.BooleanField(null=True, blank=True)

    # --- Delivery ---
    fob_point = models.CharField(max_length=50, null=True, blank=True)
    delivery_destination = models.CharField(max_length=200, null=True, blank=True)
    need_ship_date = models.DateField(null=True, blank=True)
    required_delivery_date = models.DateField(null=True, blank=True)

    # --- Packaging (replaces SolPackaging regex extraction) ---
    packaging_standard = models.CharField(max_length=100, null=True, blank=True)
    preservation_method = models.CharField(max_length=200, null=True, blank=True)
    special_packaging_instructions = models.TextField(null=True, blank=True)
    marking_standard = models.CharField(max_length=100, null=True, blank=True)

    # --- Other ---
    other_notable_requirements = models.TextField(
        null=True,
        blank=True,
        help_text="JSON array of strings stored as text",
    )
    extraction_confidence = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="HIGH / MEDIUM / LOW from LLM self-assessment",
    )
    extraction_notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "dibbs_sol_analysis"

    def __str__(self):
        return f"SolAnalysis({self.solicitation_id})"

    def get_other_notable_list(self):
        """Return other_notable_requirements as a Python list."""
        import json

        if not self.other_notable_requirements:
            return []
        try:
            return json.loads(self.other_notable_requirements)
        except Exception:
            return []
