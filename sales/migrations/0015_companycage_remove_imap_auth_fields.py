from django.db import migrations


class Migration(migrations.Migration):
    """
    Drop imap_auth_type and imap_password from CompanyCAGE.
    Exchange Online GCC High has blocked Basic auth; auth is always delegated
    OAuth 2.0 via the signed-in employee's Microsoft token.
    """

    dependencies = [
        ("sales", "0014_companycage_remove_imap_oauth_fields"),
    ]

    operations = [
        migrations.RemoveField(model_name="companycage", name="imap_auth_type"),
        migrations.RemoveField(model_name="companycage", name="imap_password"),
    ]
