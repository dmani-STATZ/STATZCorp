# Generated manually for intake SharePoint phase 1

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0071_acknowledgmentlettertemplate_sharepoint'),
        ('intake', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='draftcontract',
            name='company',
            field=models.ForeignKey(
                blank=True,
                help_text='Company this draft belongs to. Set at ingestion time.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='draft_contracts',
                to='contracts.company',
            ),
        ),
        migrations.AddField(
            model_name='draftcontract',
            name='sharepoint_folder_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('exists', 'Exists'),
                    ('not_found', 'Not Found'),
                    ('created', 'Created'),
                    ('error', 'Error'),
                ],
                default='pending',
                help_text=(
                    'Whether the SharePoint folder for this contract has been '
                    'confirmed or created.'
                ),
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name='draftcontract',
            index=models.Index(fields=['company'], name='intake_draf_company_idx'),
        ),
    ]
