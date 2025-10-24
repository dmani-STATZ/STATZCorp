from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0026_note_reminder_company'),
    ]

    operations = [
        migrations.AddField(
            model_name='contract',
            name='special_payment_terms',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.CASCADE, to='contracts.specialpaymentterms'),
        ),
    ]

