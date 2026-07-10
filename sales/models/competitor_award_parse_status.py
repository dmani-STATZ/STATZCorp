from django.db import models

from .awards import DibbsAward


class CompetitorAwardParseStatus(models.Model):
    STATUS_SUCCESS = "success"
    STATUS_PARTIAL = "partial"
    STATUS_FAILED = "failed"
    STATUS_UNAVAILABLE = "unavailable"
    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Success"),
        (STATUS_PARTIAL, "Partial"),
        (STATUS_FAILED, "Failed"),
        (STATUS_UNAVAILABLE, "Unavailable"),
    ]

    award = models.OneToOneField(
        DibbsAward,
        on_delete=models.CASCADE,
        related_name="entity_parse_status",
    )

    parse_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, blank=True, default=""
    )
    parse_notes = models.TextField(blank=True, default="")
    resolved_pdf_url = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text=(
            "Real dibbs2 Downloads/Awards PDF URL resolved from AwdRec.aspx. "
            "Cached so retries skip re-resolution."
        ),
    )
    fetch_error = models.BooleanField(default=False)
    attempt_count = models.IntegerField(default=0)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sales_competitor_award_parse_status"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Parse status for {self.award.notice_id}: {self.parse_status}"
