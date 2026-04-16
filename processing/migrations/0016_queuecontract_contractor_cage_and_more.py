from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("processing", "0015_queuecontract_pdf_parse_notes_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="queuecontract",
            name="contractor_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="queuecontract",
            name="contractor_cage",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
