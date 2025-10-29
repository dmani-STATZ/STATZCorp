from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()


class ReportRequest(models.Model):
    """Simple request-driven reporting model.

    Lifecycle:
    - User creates a request (status=pending)
    - Admin provides SQL (status=completed -> ready to run)
    - User can run/export results; or request changes (status=change)
    """

    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"  # SQL provided and ready to run
    STATUS_CHANGE = "change"  # user requested changes

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CHANGE, "Change Requested"),
    ]

    CATEGORY_CHOICES = [
        ("contract", "Contract"),
        ("supplier", "Supplier"),
        ("nsn", "NSN"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="report_requests")
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    sql_query = models.TextField(blank=True)
    context_notes = models.TextField(blank=True)
    ai_prompt = models.TextField(blank=True)
    ai_result = models.TextField(blank=True)

    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_rowcount = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - representation only
        return f"{self.title} ({self.get_status_display()})"
