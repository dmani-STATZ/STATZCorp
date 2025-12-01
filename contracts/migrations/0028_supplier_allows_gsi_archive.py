from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def map_allows_gsi_forward(apps, schema_editor):
    Supplier = apps.get_model('contracts', 'Supplier')
    for supplier in Supplier.objects.all():
        current = getattr(supplier, 'allows_gsi', None)
        if current is True:
            supplier.allows_gsi_status = 'YES'
        elif current is False:
            supplier.allows_gsi_status = 'NO'
        else:
            supplier.allows_gsi_status = 'UNK'
        supplier.save(update_fields=['allows_gsi_status'])


def map_allows_gsi_backward(apps, schema_editor):
    Supplier = apps.get_model('contracts', 'Supplier')
    for supplier in Supplier.objects.all():
        status = getattr(supplier, 'allows_gsi_status', None)
        if status == 'YES':
            supplier.allows_gsi = True
        elif status == 'NO':
            supplier.allows_gsi = False
        else:
            supplier.allows_gsi = None
        supplier.save(update_fields=['allows_gsi'])


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0027_contract_special_payment_terms'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='allows_gsi_status',
            field=models.CharField(choices=[('UNK', 'Unknown'), ('YES', 'Yes'), ('NO', 'No')], default='UNK', max_length=3),
        ),
        migrations.AddField(
            model_name='supplier',
            name='archived',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='supplier',
            name='archived_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='supplier_archived', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='supplier',
            name='archived_on',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(map_allows_gsi_forward, map_allows_gsi_backward),
        migrations.RemoveField(
            model_name='supplier',
            name='allows_gsi',
        ),
        migrations.RenameField(
            model_name='supplier',
            old_name='allows_gsi_status',
            new_name='allows_gsi',
        ),
    ]
