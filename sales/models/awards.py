from django.conf import settings
from django.db import models


class AwardImportBatch(models.Model):
    """Tracks each AW file upload. One record per imported file."""

    award_date = models.DateField()
    filename = models.CharField(max_length=50)
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dibbs_award_import_batches",
    )
    row_count = models.IntegerField(default=0)
    created_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    we_won_count = models.IntegerField(default=0)

    class Meta:
        db_table = "dibbs_award_import_batch"
        ordering = ["-imported_at"]

    def __str__(self):
        return f"AW Import {self.award_date} ({self.row_count} rows)"


class DibbsAward(models.Model):
    SOURCE_SAM = "SAM"
    SOURCE_DIBBS_FILE = "DIBBS_FILE"
    SOURCE_CHOICES = [
        (SOURCE_SAM, "SAM.gov"),
        (SOURCE_DIBBS_FILE, "DIBBS File"),
    ]

    solicitation = models.ForeignKey(
        "Solicitation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="awards",
    )
    sol_number = models.CharField(max_length=50, db_index=True)
    notice_id = models.CharField(max_length=100, unique=True)
    award_date = models.DateField()
    awardee_cage = models.CharField(max_length=10, blank=True, db_index=True)
    we_won = models.BooleanField(default=False)

    source = models.CharField(
        max_length=10,
        choices=SOURCE_CHOICES,
        default=SOURCE_SAM,
        db_index=True,
    )
    award_basic_number = models.CharField(max_length=50, null=True, blank=True)
    delivery_order_number = models.CharField(max_length=50, blank=True, default="")
    delivery_order_counter = models.CharField(max_length=20, null=True, blank=True)
    last_mod_posting_date = models.DateField(null=True, blank=True)
    total_contract_price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    posted_date = models.DateField(null=True, blank=True)
    aw_file_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Date of the AW file that last wrote this record (from filename, e.g. aw260321.txt → 2026-03-21).",
    )
    nsn = models.CharField(max_length=46, null=True, blank=True, db_index=True)
    nomenclature = models.CharField(max_length=100, null=True, blank=True)
    purchase_request = models.CharField(max_length=20, null=True, blank=True)
    dibbs_solicitation_number = models.CharField(max_length=30, null=True, blank=True)
    aw_import_batch = models.ForeignKey(
        AwardImportBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="awards",
    )

    class Meta:
        db_table = "dibbs_award"


class WeWonAward(models.Model):
    """
    Read-only unmanaged model backed by the SQL Server view
    dibbs_we_won_awards. Joins dibbs_award.awardee_cage to
    dibbs_company_cage.cage_code (active CAGEs only).
    Use: DibbsAward.objects.filter(id__in=WeWonAward.objects.values('id'))

    IMPORTANT: The view [dbo].[dibbs_we_won_awards] must exist in the
    database. It is NOT created by Django migrations — create it manually
    in SSMS. See DIBBS_System_Spec.md Section 13 for the CREATE VIEW DDL.
    """

    class Meta:
        managed = False
        db_table = "dibbs_we_won_awards"