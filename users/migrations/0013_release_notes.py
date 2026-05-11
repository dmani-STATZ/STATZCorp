import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("users", "0012_workcalendarevent_sharepoint_sync"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReleaseNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("title", models.CharField(max_length=255)),
                ("body_markdown", models.TextField()),
                ("publish_date", models.DateField(db_index=True)),
                ("change_type", models.CharField(max_length=20)),
                ("area", models.CharField(max_length=20)),
                ("critical", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-publish_date", "-note_id"],
            },
        ),
        migrations.CreateModel(
            name="ReleaseNoteAcknowledgement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("acknowledged_at", models.DateTimeField(auto_now_add=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "release_note",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="acknowledgements",
                        to="users.releasenote",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="release_note_acks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="releasenote",
            index=models.Index(fields=["publish_date", "note_id"], name="users_relea_publish_0ab0ec_idx"),
        ),
        migrations.AddConstraint(
            model_name="releasenoteacknowledgement",
            constraint=models.UniqueConstraint(fields=("user", "release_note"), name="uniq_user_release_note_ack"),
        ),
        migrations.AddIndex(
            model_name="releasenoteacknowledgement",
            index=models.Index(fields=["user", "acknowledged_at"], name="users_relea_user_id_7f8a1d_idx"),
        ),
    ]
