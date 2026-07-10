from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0058_remove_competitor_supplier_backfill_task"),
    ]

    operations = [
        migrations.AlterField(
            model_name="competitorawardparsestatus",
            name="parse_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("success", "Success"),
                    ("partial", "Partial"),
                    ("failed", "Failed"),
                    ("unavailable", "Unavailable"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
