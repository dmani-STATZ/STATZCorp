from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0047_contract_pr_number_alter_paymenthistory_payment_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="trackerschema",
            name="system_col_widths",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
