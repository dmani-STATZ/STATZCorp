from django.db import migrations, models


def copy_fat_plt_due_date_to_fat(apps, schema_editor):
    AcknowledgementLetter = apps.get_model('contracts', 'AcknowledgementLetter')
    for letter in AcknowledgementLetter.objects.exclude(fat_plt_due_date__isnull=True):
        letter.fat_due_date = letter.fat_plt_due_date
        letter.save(update_fields=['fat_due_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0069_acknowledgmentlettertemplate'),
    ]

    operations = [
        migrations.AddField(
            model_name='acknowledgementletter',
            name='fat_due_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='acknowledgementletter',
            name='plt_due_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(copy_fat_plt_due_date_to_fat, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='acknowledgementletter',
            name='fat_plt_due_date',
        ),
    ]
