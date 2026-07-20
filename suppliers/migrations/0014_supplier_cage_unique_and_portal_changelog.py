# Normalize cage_code blanks/duplicates, add unique constraint + portal change log.

from collections import defaultdict

from django.db import migrations, models
import django.db.models.deletion


def normalize_cage_codes(apps, schema_editor):
    Supplier = apps.get_model('suppliers', 'Supplier')

    # Materialize first — MSSQL cannot iterate a lazy queryset while writing.
    rows = list(Supplier.objects.values('id', 'cage_code'))

    # Blank / whitespace-only → NULL
    blank_ids = [
        row['id']
        for row in rows
        if row['cage_code'] is not None and not str(row['cage_code']).strip()
    ]
    if blank_ids:
        for i in range(0, len(blank_ids), 500):
            batch = blank_ids[i:i + 500]
            Supplier.objects.filter(id__in=batch).update(cage_code=None)

    # Refresh after blanking
    rows = list(
        Supplier.objects.exclude(cage_code__isnull=True).values('id', 'cage_code')
    )
    by_code = defaultdict(list)
    for row in rows:
        code = str(row['cage_code']).strip()
        by_code[code].append(row['id'])

    updates = []
    for code, ids in by_code.items():
        if len(ids) < 2:
            continue
        ids_sorted = sorted(ids)
        # Keep lowest pk; suffix the rest.
        for dup_id in ids_sorted[1:]:
            new_code = f"{code[:6]}-D{dup_id}"[:10]
            updates.append((dup_id, new_code))

    for dup_id, new_code in updates:
        Supplier.objects.filter(id=dup_id).update(cage_code=new_code)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('suppliers', '0013_migrate_rfq_email_to_sales_contacts'),
    ]

    operations = [
        migrations.RunPython(normalize_cage_codes, noop_reverse),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(
                condition=models.Q(('cage_code__isnull', False)),
                fields=('cage_code',),
                name='uniq_supplier_cage_code',
            ),
        ),
        migrations.CreateModel(
            name='SupplierPortalChangeLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cage_code', models.CharField(db_index=True, max_length=10)),
                ('action', models.CharField(choices=[('patch_profile', 'Patch profile'), ('create_contact', 'Create contact'), ('update_contact', 'Update contact'), ('delete_contact', 'Delete contact'), ('upload_document', 'Upload document')], db_index=True, max_length=32)),
                ('entity_type', models.CharField(choices=[('supplier', 'Supplier'), ('contact', 'Contact'), ('document', 'Document')], max_length=16)),
                ('entity_id', models.PositiveIntegerField(blank=True, null=True)),
                ('changes', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('supplier', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='portal_change_logs', to='suppliers.supplier')),
            ],
            options={
                'db_table': 'contracts_supplierportalchangelog',
                'ordering': ['-created_at'],
            },
        ),
    ]
