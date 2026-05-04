from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0051_note_note_tag"),
    ]

    operations = [
        migrations.AddField(
            model_name="clinshipment",
            name="quote_value",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=19, null=True,
                help_text="Supplier cost for this shipment. Auto-calculated but editable."
            ),
        ),
        migrations.AddField(
            model_name="clinshipment",
            name="item_value",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=19, null=True,
                help_text="Contract value for this shipment. Auto-calculated but editable."
            ),
        ),
        migrations.AddField(
            model_name="clinshipment",
            name="paid_amount",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=19, null=True,
                help_text="Amount paid by government for this partial shipment."
            ),
        ),
        migrations.AddField(
            model_name="clinshipment",
            name="wawf_payment",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=19, null=True,
                help_text="Customer pay / WAWF payment received for this partial shipment."
            ),
        ),
        migrations.AddField(
            model_name="contractfinanceline",
            name="partial",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="finance_lines",
                to="contracts.clinshipment",
                help_text="When set, this finance line is scoped to this partial shipment; when null, it is CLIN-level only.",
            ),
        ),
    ]
