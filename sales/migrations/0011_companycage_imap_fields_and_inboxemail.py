import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0010_suppliermatch_manual_method"),
    ]

    operations = [
        # IMAP fields on CompanyCAGE
        migrations.AddField(
            model_name="companycage",
            name="imap_host",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="companycage",
            name="imap_port",
            field=models.IntegerField(default=993),
        ),
        migrations.AddField(
            model_name="companycage",
            name="imap_user",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="companycage",
            name="imap_password",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="companycage",
            name="imap_folder",
            field=models.CharField(default="INBOX", max_length=100),
        ),
        migrations.AddField(
            model_name="companycage",
            name="imap_last_fetched",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # InboxEmail model
        migrations.CreateModel(
            name="InboxEmail",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.CharField(max_length=500, unique=True)),
                ("from_email", models.EmailField(max_length=254)),
                ("from_name", models.CharField(blank=True, max_length=255)),
                ("subject", models.CharField(blank=True, max_length=500)),
                ("body_text", models.TextField(blank=True)),
                ("received_at", models.DateTimeField()),
                ("fetched_at", models.DateTimeField(auto_now_add=True)),
                (
                    "rfq",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inbox_emails",
                        to="sales.supplierRFQ",
                    ),
                ),
                ("is_read", models.BooleanField(default=False)),
                ("is_matched", models.BooleanField(default=False)),
            ],
            options={
                "verbose_name": "Inbox Email",
                "verbose_name_plural": "Inbox Emails",
                "db_table": "sales_inbox_email",
                "ordering": ["-received_at"],
            },
        ),
    ]
