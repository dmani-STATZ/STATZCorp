from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0096_alter_contract_solicitation_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='contract',
            name='sharepoint_drive_item_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
    ]
