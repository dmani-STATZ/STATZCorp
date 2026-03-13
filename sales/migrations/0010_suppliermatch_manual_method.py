from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0009_email_template"),
    ]

    operations = [
        migrations.AlterField(
            model_name="suppliermatch",
            name="match_method",
            field=models.CharField(
                choices=[
                    ("DIRECT_NSN",      "Direct NSN"),
                    ("APPROVED_SOURCE", "Approved Source"),
                    ("FSC",             "FSC Category"),
                    ("MANUAL",          "Manual / Ad-hoc"),
                ],
                max_length=20,
            ),
        ),
    ]
