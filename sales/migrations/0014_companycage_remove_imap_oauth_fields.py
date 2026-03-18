from django.db import migrations


class Migration(migrations.Migration):
    """
    Remove per-CAGE OAuth2 credential fields added in 0012/0013.
    OAuth credentials are now read from settings.AZURE_AD_CONFIG so they
    are not duplicated in the database.
    """

    dependencies = [
        ("sales", "0013_companycage_imap_oauth_cloud"),
    ]

    operations = [
        migrations.RemoveField(model_name="companycage", name="imap_oauth_client_id"),
        migrations.RemoveField(model_name="companycage", name="imap_oauth_client_secret"),
        migrations.RemoveField(model_name="companycage", name="imap_oauth_tenant_id"),
        migrations.RemoveField(model_name="companycage", name="imap_oauth_cloud"),
    ]
