from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0070_split_fat_plt_due_dates'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='acknowledgmentlettertemplate',
            name='file',
        ),
        migrations.AddField(
            model_name='acknowledgmentlettertemplate',
            name='sharepoint_file_id',
            field=models.CharField(default='', max_length=500),
        ),
        migrations.AddField(
            model_name='acknowledgmentlettertemplate',
            name='sharepoint_file_name',
            field=models.CharField(default='', max_length=255),
        ),
    ]
