from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("processing", "0016_queuecontract_contractor_cage_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="queuecontract",
            name="description",
            field=models.TextField(
                blank=True,
                null=True,
                help_text=(
                    "Shadow-schema metadata for special contract types. "
                    "IDIQ format: IDIQ_META|TERM:<months>|MAX:<value>|MIN:<value>"
                ),
            ),
        ),
    ]
