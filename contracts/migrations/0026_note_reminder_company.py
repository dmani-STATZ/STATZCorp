from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0025_company_branding'),
    ]

    operations = [
        migrations.AddField(
            model_name='note',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='notes', to='contracts.company'),
        ),
        migrations.AddField(
            model_name='reminder',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reminders', to='contracts.company'),
        ),
    ]

