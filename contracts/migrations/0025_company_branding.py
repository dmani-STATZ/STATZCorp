from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0024_company_logo'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='primary_color',
            field=models.CharField(max_length=7, null=True, blank=True, help_text='Hex color like #004eb3'),
        ),
        migrations.AddField(
            model_name='company',
            name='secondary_color',
            field=models.CharField(max_length=7, null=True, blank=True, help_text='Hex color like #e5e7eb'),
        ),
    ]

