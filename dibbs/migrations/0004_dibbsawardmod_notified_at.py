from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dibbs', '0003_drop_sales_workflow_columns'),
    ]

    operations = [
        migrations.AddField(
            model_name='dibbsawardmod',
            name='notified_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the new-mod email went out. NULL = not sent (or send failed).',
                null=True,
            ),
        ),
    ]
