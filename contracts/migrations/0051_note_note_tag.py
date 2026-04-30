from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0050_seed_finance_line_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='note',
            name='note_tag',
            field=models.CharField(blank=True, default='', max_length=20, null=True),
        ),
    ]
