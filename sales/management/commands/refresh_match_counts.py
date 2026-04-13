"""
Management command: refresh_match_counts

Reads (solicitation_id, match_count) pairs from the dibbs_solicitation_match_counts
SQL Server view via the SolicitationMatchCount unmanaged model, then bulk-updates
Solicitation.match_count for all rows in the view and zeros out any rows not present.

Chunked at 200 IDs per query to stay under SQL Server's 2,100 parameter limit.
Does NOT use bulk_update — django-mssql-backend breaks on OUTPUT INSERTED.id.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from sales.models import Solicitation, SolicitationMatchCount

CHUNK_SIZE = 200


def _chunked(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


class Command(BaseCommand):
    help = "Refresh Solicitation.match_count from the dibbs_solicitation_match_counts view."

    def handle(self, *args, **options):
        # Build dict: {match_count_value: [sol_id, ...]}
        count_to_ids = defaultdict(list)
        all_ids_in_view = set()

        for row in SolicitationMatchCount.objects.values('solicitation_id', 'match_count'):
            sol_id = row['solicitation_id']
            mc = row['match_count']
            count_to_ids[mc].append(sol_id)
            all_ids_in_view.add(sol_id)

        updated_total = 0

        # Update rows that appear in the view, grouped by match_count value.
        for mc_value, id_list in count_to_ids.items():
            for chunk in _chunked(id_list, CHUNK_SIZE):
                n = Solicitation.objects.filter(id__in=chunk).update(match_count=mc_value)
                updated_total += n

        # Zero out any Solicitation rows whose id was NOT in the view results.
        # Compute the set difference in Python to avoid a giant SQL IN clause.
        all_sol_ids = list(Solicitation.objects.values_list('id', flat=True))
        ids_to_zero = [sid for sid in all_sol_ids if sid not in all_ids_in_view]
        for chunk in _chunked(ids_to_zero, CHUNK_SIZE):
            Solicitation.objects.filter(id__in=chunk).update(match_count=0)

        self.stdout.write(f"Refreshed match_count on {updated_total} solicitations.")
