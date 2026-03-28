"""
Solicitation, SolicitationLine, ImportBatch — Section 3.1.
Tables: dibbs_solicitation, dibbs_solicitation_line, tbl_ImportBatch.
"""
from django.db import models
from django.utils import timezone


class ImportBatch(models.Model):
    """Tracks each daily DIBBS file import (IN, BQ, AS)."""
    import_date = models.DateField()
    in_file_name = models.CharField(max_length=50, null=True, blank=True)
    bq_file_name = models.CharField(max_length=50, null=True, blank=True)
    as_file_name = models.CharField(max_length=50, null=True, blank=True)
    imported_at = models.DateTimeField()
    solicitation_count = models.IntegerField(default=0)
    imported_by = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = 'tbl_ImportBatch'
        verbose_name = 'Import batch'
        verbose_name_plural = 'Import batches'


class ImportJob(models.Model):
    """
    Tracks a multi-step AJAX import in progress.
    Created when files are uploaded; updated as each step completes.
    Allows the progress page to survive a browser refresh.
    """
    STATUS_UPLOADED   = 'uploaded'
    STATUS_PARSING    = 'parsing'
    STATUS_SOLS       = 'solicitations'
    STATUS_LINES      = 'lines'
    STATUS_MATCHING   = 'matching'
    STATUS_COMPLETE   = 'complete'
    STATUS_ERROR      = 'error'

    job_id        = models.CharField(max_length=36, unique=True)   # UUID
    status        = models.CharField(max_length=20, default=STATUS_UPLOADED)
    in_file_path  = models.CharField(max_length=500, null=True, blank=True)
    bq_file_path  = models.CharField(max_length=500, null=True, blank=True)
    as_file_path  = models.CharField(max_length=500, null=True, blank=True)
    in_file_name  = models.CharField(max_length=100, null=True, blank=True)
    bq_file_name  = models.CharField(max_length=100, null=True, blank=True)
    as_file_name  = models.CharField(max_length=100, null=True, blank=True)
    import_date   = models.DateField(null=True, blank=True)
    batch_id      = models.IntegerField(null=True, blank=True)   # FK to ImportBatch after step 1
    step_results  = models.TextField(default='{}')               # JSON: accumulated per-step results
    imported_by   = models.CharField(max_length=100, null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'tbl_ImportJob'
        verbose_name = 'Import job'


class Solicitation(models.Model):
    """One row per solicitation (from IN/BQ)."""
    STATUS_CHOICES = [
        ('New', 'New'),
        ('Active', 'Active'),
        ('Matching', 'Matching'),
        ('RFQ_PENDING', 'RFQ Pending'),
        ('RFQ_SENT', 'RFQ Sent'),
        ('QUOTING', 'Quoting'),
        ('BID_READY', 'Bid Ready'),
        ('BID_SUBMITTED', 'Bid Submitted'),
        ('WON', 'Won'),
        ('LOST', 'Lost'),
        ('NO_BID', 'No Bid'),
        ('Archived', 'Archived'),
    ]
    BUCKET_CHOICES = [
        ('UNSET', 'Not Yet Triaged'),
        ('SDVOSB', 'SDVOSB Priority'),
        ('HUBZONE', 'HUBZone'),
        ('GROWTH', 'Growth'),
        ('SKIP', 'Skip'),
    ]
    BUCKET_ASSIGNED_BY_CHOICES = [
        ('auto', 'Auto'),
        ('manual', 'Manual'),
        ('hubzone', 'HUBZone'),
    ]
    solicitation_number = models.CharField(max_length=13, unique=True, db_index=True)
    solicitation_type = models.CharField(max_length=1, null=True, blank=True)  # F/I/P
    small_business_set_aside = models.CharField(max_length=1, null=True, blank=True)  # N/Y/H/R/L/A/E
    return_by_date = models.DateField(null=True, blank=True)
    pdf_file_name = models.CharField(max_length=50, null=True, blank=True)
    buyer_code = models.CharField(max_length=5, null=True, blank=True)
    import_date = models.DateField(null=True, blank=True)
    import_batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solicitations',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='New')
    bucket = models.CharField(
        max_length=10,
        choices=BUCKET_CHOICES,
        default='UNSET',
        db_index=True,
    )
    bucket_assigned_by = models.CharField(
        max_length=10,
        choices=BUCKET_ASSIGNED_BY_CHOICES,
        null=True,
        blank=True,
    )
    hubzone_requested_by = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Name or note from HUBZone partner who requested this solicitation be worked.",
    )
    pdf_blob = models.BinaryField(null=True, blank=True)
    pdf_fetched_at = models.DateTimeField(null=True, blank=True)

    PDF_FETCH_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("FETCHING", "Fetching"),
        ("DONE", "Done"),
        ("FAILED", "Failed"),
    ]
    pdf_fetch_status = models.CharField(
        max_length=10,
        choices=PDF_FETCH_STATUS_CHOICES,
        null=True,
        blank=True,
        default=None,
        db_index=True,
    )
    pdf_fetch_attempts = models.PositiveSmallIntegerField(default=0)
    pdf_data_pulled = models.DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Set when procurement history data has been extracted from this sol's PDF, "
            "either via CA zip or individual fetch."
        ),
    )

    class Meta:
        db_table = 'dibbs_solicitation'
        verbose_name = 'Solicitation'
        verbose_name_plural = 'Solicitations'

    @property
    def days_remaining(self):
        """Days until return_by_date; None if no date or already past."""
        if not self.return_by_date:
            return None
        today = timezone.now().date()
        delta = (self.return_by_date - today).days
        return max(0, delta) if delta >= 0 else 0

    @property
    def dibbs_pdf_url(self):
        if self.pdf_file_name and self.solicitation_number:
            subdir = self.solicitation_number[-1].upper()
            return f"https://dibbs2.bsm.dla.mil/Downloads/RFQ/{subdir}/{self.pdf_file_name.upper()}"
        return None


class SolicitationLine(models.Model):
    """One row per NSN/line within a solicitation."""
    solicitation = models.ForeignKey(
        Solicitation,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    line_number = models.CharField(max_length=4, null=True, blank=True)
    purchase_request_number = models.CharField(max_length=13, null=True, blank=True)
    nsn = models.CharField(max_length=46, db_index=True)
    fsc = models.CharField(max_length=4, null=True, blank=True)
    niin = models.CharField(max_length=9, null=True, blank=True)
    unit_of_issue = models.CharField(max_length=2, null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    delivery_days = models.IntegerField(null=True, blank=True)
    nomenclature = models.CharField(max_length=21, null=True, blank=True)
    amsc = models.CharField(max_length=1, null=True, blank=True)
    item_type_indicator = models.CharField(max_length=1, null=True, blank=True)
    item_description_indicator = models.CharField(max_length=1, null=True, blank=True)
    trade_agreements_indicator = models.CharField(max_length=1, null=True, blank=True)
    buy_american_indicator = models.CharField(max_length=1, null=True, blank=True)
    higher_level_quality_indicator = models.CharField(max_length=1, null=True, blank=True)
    # Original BQ row (121 columns) for export overlay; populated at import when BQ file present
    bq_raw_columns = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'dibbs_solicitation_line'
        verbose_name = 'Solicitation line'
        verbose_name_plural = 'Solicitation lines'


class NsnProcurementHistory(models.Model):
    """
    Historical DLA purchase records for a given NSN, extracted from DIBBS
    solicitation ZIP blobs at PDF fetch time.

    Keyed on NSN + contract_number. The solicitation is provenance only —
    this data belongs to the NSN, not any single solicitation.
    """
    nsn = models.CharField(
        max_length=13,
        db_index=True,
        help_text="Normalized 13-digit NSN, no hyphens. e.g. 5935011299512",
    )
    fsc = models.CharField(
        max_length=4,
        db_index=True,
        help_text="First 4 chars of NSN — FSC code",
    )
    cage_code = models.CharField(max_length=5)
    contract_number = models.CharField(max_length=25)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=5)
    award_date = models.DateField()
    surplus_material = models.BooleanField(default=False)
    # Provenance — which solicitation surface did we first/last see this row on
    first_seen_sol = models.CharField(
        max_length=13,
        blank=True,
        help_text="Solicitation number where this row was first extracted",
    )
    last_seen_sol = models.CharField(
        max_length=13,
        blank=True,
        help_text="Solicitation number where this row was most recently seen",
    )
    extracted_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "dibbs_nsn_procurement_history"
        unique_together = [("nsn", "contract_number")]
        ordering = ["-award_date"]
        verbose_name = "NSN Procurement History"
        verbose_name_plural = "NSN Procurement History"

    def __str__(self):
        return f"{self.nsn} — {self.contract_number} @ ${self.unit_cost}"
