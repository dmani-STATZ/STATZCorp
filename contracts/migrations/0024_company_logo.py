from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0023_company_alter_foldertracking_stack_id_clin_company_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='logo',
            field=models.FileField(upload_to='company-logos/', null=True, blank=True),
        ),
    ]

