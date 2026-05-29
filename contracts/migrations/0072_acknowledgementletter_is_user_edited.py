from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0071_acknowledgmentlettertemplate_sharepoint'),
    ]

    operations = [
        migrations.AddField(
            model_name='acknowledgementletter',
            name='is_user_edited',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Set to True when the letter is sent to the contract folder. '
                    'While False, the prefill logic re-runs on every page open, '
                    'overwriting all fields with current contract data.'
                ),
            ),
        ),
    ]
