# Generated manually for ProcessClinSplit (per-CLIN staging splits)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('processing', '0018_add_sharepoint_status_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProcessClinSplit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('company_name', models.CharField(max_length=100)),
                (
                    'split_value',
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=19, null=True
                    ),
                ),
                (
                    'split_paid',
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=19, null=True
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                (
                    'clin',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='splits',
                        to='processing.processclin',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Process CLIN Split',
                'verbose_name_plural': 'Process CLIN Splits',
                'db_table': 'processing_processclin_split',
                'ordering': ['company_name'],
            },
        ),
        migrations.DeleteModel(
            name='ProcessContractSplit',
        ),
    ]
