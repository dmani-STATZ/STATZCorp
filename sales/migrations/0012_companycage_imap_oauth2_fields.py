from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0011_companycage_imap_fields_and_inboxemail"),
    ]

    operations = [
        migrations.AddField(
            model_name="companycage",
            name="imap_auth_type",
            field=models.CharField(
                choices=[
                    ("BASIC", "Basic (username / password)"),
                    ("OAUTH2", "OAuth 2.0 \u2014 Microsoft 365 / Exchange Online"),
                ],
                default="BASIC",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="companycage",
            name="imap_oauth_client_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="companycage",
            name="imap_oauth_client_secret",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name="companycage",
            name="imap_oauth_tenant_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
