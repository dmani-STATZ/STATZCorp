from django.core.management.base import BaseCommand

from products.models import Nsn
from products.nsn_utils import normalize_nsn


class Command(BaseCommand):
    help = (
        'Idempotent backfill of Nsn.nsn_normalized for rows where the stored '
        'value differs from normalize_nsn(nsn_code). Run after bulk SQL MERGEs '
        'into contracts_nsn that bypass the ORM. Values that normalize to more '
        'than 13 characters are left blank (see list_unnormalized_nsns).'
    )

    def handle(self, *args, **options):
        updated = 0
        flagged = 0
        batch = []
        rows = list(
            Nsn.objects.all().only('pk', 'nsn_code', 'nsn_normalized').iterator(chunk_size=2000)
        )
        for row in rows:
            computed = normalize_nsn(row.nsn_code or '')
            if len(computed) > 13:
                flagged += 1
                if row.nsn_normalized != '':
                    row.nsn_normalized = ''
                    batch.append(row)
                continue
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
        if flagged:
            self.stdout.write(
                self.style.WARNING(
                    f'{flagged} row(s) exceed 13 normalized characters and were '
                    f'left blank. Run `python manage.py list_unnormalized_nsns`.'
                )
            )
