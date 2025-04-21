from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('contracts', '0015_contract_contract_prime_idx_and_more'),  # You'll need to adjust this to your last migration
    ]

    operations = [
        migrations.RemoveField(
            model_name='paymenthistory',
            name='created_by',
        ),
        migrations.RemoveField(
            model_name='paymenthistory',
            name='updated_by',
        ),
        migrations.DeleteModel(
            name='PaymentHistory',
        ),
    ] 