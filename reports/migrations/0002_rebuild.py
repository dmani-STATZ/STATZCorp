from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ReportRequest",
        ),
        migrations.CreateModel(
            name="ReportDraft",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("original_prompt", models.TextField()),
                ("latest_feedback", models.TextField(blank=True)),
                ("current_sql", models.TextField(blank=True)),
                ("current_tags", models.JSONField(default=list)),
                ("current_title", models.CharField(blank=True, max_length=200)),
                ("ai_iteration_count", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="report_drafts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="Report",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                (
                    "visibility",
                    models.CharField(
                        choices=[("personal", "Personal"), ("company", "Company")],
                        default="personal",
                        max_length=20,
                    ),
                ),
                ("tags", models.JSONField(default=list)),
                (
                    "source",
                    models.CharField(
                        choices=[("requested", "Requested"), ("prototyped", "Prototyped")],
                        default="requested",
                        max_length=20,
                    ),
                ),
                ("branch_count", models.IntegerField(default=0)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_run_rowcount", models.IntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "branched_from",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="branches",
                        to="reports.report",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="owned_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source_draft",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="spawned_reports",
                        to="reports.reportdraft",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ReportRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("in_progress", "In Progress"),
                            ("completed", "Completed"),
                            ("change_requested", "Change Requested"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("description", models.TextField()),
                ("admin_notes", models.TextField(blank=True)),
                ("keep_original", models.BooleanField(default=False)),
                ("is_branch_request", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "linked_report",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="source_requests",
                        to="reports.report",
                    ),
                ),
                (
                    "requester",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="report_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddField(
            model_name="report",
            name="source_request",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="spawned_reports",
                to="reports.reportrequest",
            ),
        ),
        migrations.CreateModel(
            name="ReportVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("version_number", models.PositiveIntegerField()),
                ("sql_query", models.TextField()),
                ("context_notes", models.TextField(blank=True)),
                ("change_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="report_versions_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="reports.report",
                    ),
                ),
            ],
            options={
                "ordering": ["report", "version_number"],
                "unique_together": {("report", "version_number")},
            },
        ),
        migrations.AddField(
            model_name="report",
            name="active_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="active_for_reports",
                to="reports.reportversion",
            ),
        ),
        migrations.CreateModel(
            name="ReportShare",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("can_branch", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shares",
                        to="reports.report",
                    ),
                ),
                (
                    "shared_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports_shared_by_me",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "shared_with",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports_shared_with_me",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "unique_together": {("report", "shared_with")},
            },
        ),
    ]
