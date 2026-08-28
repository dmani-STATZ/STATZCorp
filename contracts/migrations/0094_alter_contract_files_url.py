from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contracts", "0093_remove_stale_late_flags"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contract",
            name="files_url",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
    ]
