# Normalize cage_code, add filtered unique constraint + portal change log.
# Production has duplicate non-null CAGE values; clear extras before the unique index.

from django.db import migrations, models, transaction
import django.db.models.deletion
from django.db.models import Count, Q, Value
from django.db.models.functions import Replace, Trim, Upper

_BATCH = 500


def normalize_cage_codes(apps, schema_editor):
    Supplier = apps.get_model('suppliers', 'Supplier')
    Supplier.objects.filter(cage_code__isnull=False).update(
        cage_code=Upper(
            Trim(
                Replace(
                    Replace(
                        Replace('cage_code', Value('\r'), Value('')),
                        Value('\n'),
                        Value(''),
                    ),
                    Value('\t'),
                    Value(''),
                )
            )
        )
    )
    Supplier.objects.filter(cage_code__in=['', 'NONE', 'NO CAGE']).update(cage_code=None)


def clear_duplicate_cage_codes(apps, schema_editor):
    """Keep one row per CAGE (prefer active, then lowest id); NULL the rest.

    MSSQL/pyodbc: materialize reads before any writes (no MARS).
    """
    Supplier = apps.get_model('suppliers', 'Supplier')

    dup_codes = list(
        Supplier.objects.exclude(cage_code__isnull=True)
        .exclude(cage_code='')
        .values('cage_code')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
        .values_list('cage_code', flat=True)
    )
    if not dup_codes:
        return

    extra_ids = []
    for code in dup_codes:
        rows = list(
            Supplier.objects.filter(cage_code=code)
            .order_by('id')
            .values('id', 'archived')
        )
        keep_id = next(
            (row['id'] for row in rows if row['archived'] is False),
            rows[0]['id'],
        )
        extra_ids.extend(row['id'] for row in rows if row['id'] != keep_id)

    for i in range(0, len(extra_ids), _BATCH):
        chunk = extra_ids[i : i + _BATCH]
        with transaction.atomic():
            Supplier.objects.filter(id__in=chunk).update(cage_code=None)

    print(
        f"clear_duplicate_cage_codes: nulled cage_code on {len(extra_ids)} "
        f"supplier row(s) across {len(dup_codes)} duplicate CAGE value(s)."
    )


class Migration(migrations.Migration):

    dependencies = [
        ('suppliers', '0013_migrate_rfq_email_to_sales_contacts'),
    ]

    operations = [
        migrations.RunPython(normalize_cage_codes, migrations.RunPython.noop),
        migrations.RunPython(clear_duplicate_cage_codes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(
                # Use __gt='' (not ~Q(...)): mssql-django emits NOT (...) which
                # SQL Server rejects in filtered unique index WHERE clauses.
                condition=Q(cage_code__isnull=False) & Q(cage_code__gt=''),
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
