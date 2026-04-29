import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0002_rebuild"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportrequest",
            name="parent_version",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "The specific ReportVersion that was active when this change request was submitted. "
                    "Captured at submission time so the admin sees exactly what the user was looking at."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="change_requests",
                to="reports.reportversion",
            ),
        ),
    ]
