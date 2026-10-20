"""Read-only report of IDIQs that share a normalized contract number."""
from collections import defaultdict

from django.core.management.base import BaseCommand

from contracts.models import IdiqContract, get_idiq_dependents
from contracts.services.contract_number import normalize_idiq_number


class Command(BaseCommand):
    help = 'List IDIQ records that share a normalized contract number. Read-only.'

    def handle(self, *args, **options):
        groups = defaultdict(list)
        for idiq in list(IdiqContract.objects.order_by('pk')):
            key = normalize_idiq_number(idiq.contract_number)
            if key:
                groups[key].append(idiq)

        duplicate_groups = [(key, rows) for key, rows in sorted(groups.items()) if len(rows) > 1]
        for key, rows in duplicate_groups:
            self.stdout.write(f'{key} ({len(rows)} records)')
            for idiq in rows:
                dependents = get_idiq_dependents(idiq)
                dependents_text = ', '.join(f'{label}={count}' for label, count in dependents) or 'none'
                created = idiq.created_on.date().isoformat() if idiq.created_on else '-'
                self.stdout.write(
                    f'  pk={idiq.pk}  number={idiq.contract_number!r}  '
                    f'status={"Closed" if idiq.closed else "Open"}  created={created}  '
                    f'drive_item={"yes" if idiq.sharepoint_drive_item_id else "no"}  '
                    f'dependents: {dependents_text}'
                )

        self.stdout.write(f'Duplicate groups: {len(duplicate_groups)}')
