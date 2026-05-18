from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0065_clin_fix_tool'),
    ]

    operations = [
        migrations.AddField(
            model_name='clinshipment',
            name='name',
            field=models.CharField(
                blank=True,
                help_text="User-defined shipment name (e.g. 'Shipment 1'). Defaults to 'Shipment N' display when blank.",
                max_length=100,
                null=True,
            ),
        ),
    ]
