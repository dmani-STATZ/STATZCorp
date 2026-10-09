from django.conf import settings
from django.db import models
from django.utils import timezone


class ScanFilingLog(models.Model):
    class Action(models.TextChoices):
        FILED = "FILED", "Filed"
        SKIPPED = "SKIPPED", "Skipped"
        FAILED = "FAILED", "Failed"

    created_at = models.DateTimeField(default=timezone.now)
    action = models.CharField(max_length=10, choices=Action.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="scan_filing_logs",
    )
    mailbox = models.CharField(max_length=320, blank=True, default="")
    message_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    internet_message_id = models.CharField(max_length=500, blank=True, default="")
    received_at = models.DateTimeField(null=True, blank=True)
    attachment_name = models.CharField(max_length=255, blank=True, default="")
    attachment_size = models.IntegerField(default=0)
    contract = models.ForeignKey(
        "contracts.Contract",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="scan_filing_logs",
    )
    idiq_contract = models.ForeignKey(
        "contracts.IdiqContract",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="scan_filing_logs",
    )
    contract_number = models.CharField(max_length=100, blank=True, default="")
    destination_kind = models.CharField(max_length=20, blank=True, default="")
    folder_item_id = models.CharField(max_length=255, blank=True, default="")
    folder_path = models.CharField(max_length=400, blank=True, default="")
    folder_created = models.BooleanField(default=False)
    uploaded_item_id = models.CharField(max_length=255, blank=True, default="")
    uploaded_name = models.CharField(max_length=255, blank=True, default="")
    already_present = models.BooleanField(default=False)
    skip_reason = models.CharField(max_length=200, blank=True, default="")
    error = models.CharField(max_length=1000, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        db_table = "tools_scan_filing_log"

    def __str__(self) -> str:
        return f"{self.action} {self.attachment_name or '(email)'} @ {self.created_at}"
