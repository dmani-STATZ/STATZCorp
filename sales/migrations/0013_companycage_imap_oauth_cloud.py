from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0012_companycage_imap_oauth2_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="companycage",
            name="imap_oauth_cloud",
            field=models.CharField(
                choices=[
                    ("COMMERCIAL", "Commercial (.com)"),
                    ("GCCHIGH", "GCC High (.us)"),
                ],
                default="COMMERCIAL",
                max_length=20,
            ),
        ),
    ]
