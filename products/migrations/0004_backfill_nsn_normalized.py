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
    flagged = []
    rows = list(
        Nsn.objects.all().only('pk', 'nsn_code', 'nsn_normalized').iterator(chunk_size=2000)
    )
    for row in rows:
        computed = _normalize_nsn(row.nsn_code or '')
        if len(computed) > 13:
            flagged.append((row.pk, row.nsn_code))
            if row.nsn_normalized != '':
                row.nsn_normalized = ''
                batch.append(row)
            continue
        if row.nsn_normalized != computed:
            row.nsn_normalized = computed
            batch.append(row)
        if len(batch) >= 2000:
            Nsn.objects.bulk_update(batch, ['nsn_normalized'], batch_size=2000)
            batch = []
    if batch:
        Nsn.objects.bulk_update(batch, ['nsn_normalized'], batch_size=2000)

    if flagged:
        print(
            f"\n[0004_backfill_nsn_normalized] {len(flagged)} row(s) exceed 13 normalized "
            f"characters and were left blank for manual cleanup:"
        )
        for pk, code in flagged:
            print(f"  id={pk} nsn_code={code!r}")
        print("Run `python manage.py list_unnormalized_nsns` any time to regenerate this list.\n")


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0003_nsn_normalized'),
    ]

    operations = [
        migrations.RunPython(backfill_nsn_normalized, migrations.RunPython.noop),
    ]
