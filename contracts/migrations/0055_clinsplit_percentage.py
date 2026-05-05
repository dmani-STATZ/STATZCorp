from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0054_alter_clin_paid_date_alter_clin_wawf_recieved_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="clinsplit",
            name="percentage",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Split percentage for this company on this CLIN (e.g. 60.00 = 60%). Percentages across all splits for a given CLIN should sum to 100. Used by Recalc Splits to compute split_value from Adj Gross.",
                max_digits=5,
                null=True,
            ),
        ),
    ]
