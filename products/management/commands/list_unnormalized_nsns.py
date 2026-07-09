from django.core.management.base import BaseCommand

from products.models import Nsn
from products.nsn_utils import normalize_nsn


class Command(BaseCommand):
    help = (
        "Lists Nsn rows whose nsn_code normalizes to more than 13 characters. "
        "These are left with a blank nsn_normalized and need manual data cleanup."
    )

    def handle(self, *args, **options):
        flagged = []
        for nsn in Nsn.objects.all().only('id', 'nsn_code').iterator(chunk_size=2000):
            computed = normalize_nsn(nsn.nsn_code or '')
            if len(computed) > 13:
                flagged.append((nsn.id, nsn.nsn_code, computed, len(computed)))

        if not flagged:
            self.stdout.write(self.style.SUCCESS("No flagged NSN rows found."))
            return

        self.stdout.write(self.style.WARNING(f"{len(flagged)} flagged row(s):"))
        for pk, code, computed, length in flagged:
            self.stdout.write(f"  id={pk} nsn_code={code!r} normalized_len={length}")
