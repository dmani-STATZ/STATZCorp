import re

from django.db import migrations

_NON_ALNUM_RE = re.compile(r'[^A-Za-z0-9]')


def _normalize_nsn(value):
    if not value:
        return ''
    return _NON_ALNUM_RE.sub('', value).upper()


def backfill_nsn_normalized(apps, schema_editor):
    Nsn = apps.get_model('products', 'Nsn')
    batch = []
    for row in Nsn.objects.all().only('pk', 'nsn_code', 'nsn_normalized').iterator(chunk_size=2000):
        computed = _normalize_nsn(row.nsn_code or '')
        if row.nsn_normalized != computed:
            row.nsn_normalized = computed
            batch.append(row)
        if len(batch) >= 2000:
            Nsn.objects.bulk_update(batch, ['nsn_normalized'], batch_size=2000)
            batch = []
    if batch:
        Nsn.objects.bulk_update(batch, ['nsn_normalized'], batch_size=2000)


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0003_nsn_normalized'),
    ]

    operations = [
        migrations.RunPython(backfill_nsn_normalized, migrations.RunPython.noop),
    ]
