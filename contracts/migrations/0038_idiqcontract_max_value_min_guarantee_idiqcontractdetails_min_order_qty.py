from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0037_company_sharepoint_urls"),
    ]

    operations = [
        migrations.AddField(
            model_name="idiqcontract",
            name="max_value",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=19, null=True),
        ),
        migrations.AddField(
            model_name="idiqcontract",
            name="min_guarantee",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=19, null=True),
        ),
        migrations.AddField(
            model_name="idiqcontractdetails",
            name="min_order_qty",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
