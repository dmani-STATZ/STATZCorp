import uuid

from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class ReportDraft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="report_drafts",
    )
    original_prompt = models.TextField()
    latest_feedback = models.TextField(blank=True)
    current_sql = models.TextField(blank=True)
    current_tags = models.JSONField(default=list)
    current_title = models.CharField(max_length=200, blank=True)
    ai_iteration_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.current_title or f"Draft {self.pk}"


class ReportRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CHANGE_REQUESTED = "change_requested"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CHANGE_REQUESTED, "Change Requested"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="report_requests",
    )
    linked_report = models.ForeignKey(
        "Report",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    description = models.TextField()
    admin_notes = models.TextField(blank=True)
    keep_original = models.BooleanField(default=False)
    is_branch_request = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Request {self.pk} ({self.get_status_display()})"


class Report(models.Model):
    VISIBILITY_PERSONAL = "personal"
    VISIBILITY_COMPANY = "company"

    VISIBILITY_CHOICES = [
        (VISIBILITY_PERSONAL, "Personal"),
        (VISIBILITY_COMPANY, "Company"),
    ]

    SOURCE_REQUESTED = "requested"
    SOURCE_PROTOTYPED = "prototyped"

    SOURCE_CHOICES = [
        (SOURCE_REQUESTED, "Requested"),
        (SOURCE_PROTOTYPED, "Prototyped"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owned_reports",
    )
    title = models.CharField(max_length=200)
    visibility = models.CharField(
        max_length=20,
        choices=VISIBILITY_CHOICES,
        default=VISIBILITY_PERSONAL,
    )
    tags = models.JSONField(default=list)
    active_version = models.ForeignKey(
        "ReportVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for_reports",
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_REQUESTED,
    )
    source_request = models.ForeignKey(
        ReportRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="spawned_reports",
    )
    source_draft = models.ForeignKey(
        ReportDraft,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="spawned_reports",
    )
    branched_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches",
    )
    branch_count = models.IntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_rowcount = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class ReportVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    sql_query = models.TextField()
    context_notes = models.TextField(blank=True)
    change_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="report_versions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["report", "version_number"]
        unique_together = [("report", "version_number")]

    def __str__(self) -> str:
        return f"{self.report.title} v{self.version_number}"


class ReportShare(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="shares",
    )
    shared_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="reports_shared_by_me",
    )
    shared_with = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="reports_shared_with_me",
    )
    can_branch = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("report", "shared_with")]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.report.title} -> {self.shared_with}"
