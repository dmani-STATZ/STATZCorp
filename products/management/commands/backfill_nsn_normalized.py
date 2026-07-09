import re

from django.core.management.base import BaseCommand

from products.models import Nsn

_NON_ALNUM_RE = re.compile(r'[^A-Za-z0-9]')


def _normalize_nsn(value):
    if not value:
        return ''
    return _NON_ALNUM_RE.sub('', value).upper()


class Command(BaseCommand):
    help = (
        'Idempotent backfill of Nsn.nsn_normalized for rows where the stored '
        'value differs from normalize_nsn(nsn_code). Run after bulk SQL MERGEs '
        'into contracts_nsn that bypass the ORM.'
    )

    def handle(self, *args, **options):
        updated = 0
        batch = []
        rows = list(
            Nsn.objects.all().only('pk', 'nsn_code', 'nsn_normalized').iterator(chunk_size=2000)
        )
        for row in rows:
            computed = _normalize_nsn(row.nsn_code or '')
            if row.nsn_normalized != computed:
                row.nsn_normalized = computed
                batch.append(row)
            if len(batch) >= 2000:
                Nsn.objects.bulk_update(batch, ['nsn_normalized'], batch_size=2000)
                updated += len(batch)
                batch = []
        if batch:
            Nsn.objects.bulk_update(batch, ['nsn_normalized'], batch_size=2000)
            updated += len(batch)
        self.stdout.write(self.style.SUCCESS(f'Updated {updated} row(s).'))
