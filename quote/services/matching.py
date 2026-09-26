"""
Solicitation state seeding + supplier matching for freshly imported DIBBS batches.

Runs from the ``dibbs.signals.import_completed`` receiver (quote/signals.py).
Matching is additive and idempotent: re-running it only adds missing
(solicitation, supplier, source) rows and never removes a manual match.

SQL Server notes: every ``__in`` list is chunked well under the 2,100-parameter
limit, and inserts are chunked the same way the dibbs importer does.
"""
import logging

from django.db import transaction
from django.utils import timezone

from dibbs.models import Solicitation, SolicitationLine
from quote.models import (
    QuoteSolicitation,
    QuoteSolicitationMatch,
    QuoteSupplierFSC,
    QuoteSupplierNSN,
)

logger = logging.getLogger(__name__)

IN_CHUNK = 1000      # values per __in lookup
INSERT_CHUNK = 200   # rows per bulk_create


def _chunked(items, n):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def normalize_nsn(raw) -> str:
    """Digits only; a 13-digit NSN or '' when the input isn't one."""
    digits = ''.join(ch for ch in (raw or '') if ch.isdigit())
    return digits if len(digits) == 13 else ''


def seed_solicitation_states(solicitation_ids) -> int:
    """
    Create a QuoteSolicitation for each id that has none yet. A solicitation
    already past its return-by date starts ARCHIVED, everything else UNMATCHED.
    Returns the number of rows created.
    """
    today = timezone.now().date()
    created = 0
    for chunk in _chunked(solicitation_ids, IN_CHUNK):
        missing = list(
            Solicitation.objects.filter(pk__in=chunk, quote_state__isnull=True)
            .values_list('pk', 'return_by_date')
        )
        rows = [
            QuoteSolicitation(
                solicitation_id=pk,
                status=(
                    QuoteSolicitation.STATUS_ARCHIVED
                    if return_by and return_by < today
                    else QuoteSolicitation.STATUS_UNMATCHED
                ),
            )
            for pk, return_by in missing
        ]
        for insert_chunk in _chunked(rows, INSERT_CHUNK):
            QuoteSolicitation.objects.bulk_create(insert_chunk)
        created += len(rows)
    return created


def match_solicitations(solicitation_ids) -> dict:
    """
    Link suppliers to the given solicitations by NSN and FSC capability, then
    move UNMATCHED solicitations that gained a supplier to MATCHED.
    """
    lines = []
    for chunk in _chunked(solicitation_ids, IN_CHUNK):
        lines.extend(
            SolicitationLine.objects.filter(solicitation_id__in=chunk)
            .values_list('solicitation_id', 'nsn', 'fsc')
        )

    sols_by_nsn, sols_by_fsc = {}, {}
    for sol_id, nsn, fsc in lines:
        nsn13 = normalize_nsn(nsn)
        if nsn13:
            sols_by_nsn.setdefault(nsn13, set()).add(sol_id)
        fsc4 = (fsc or nsn13[:4] or '').strip()
        if len(fsc4) == 4:
            sols_by_fsc.setdefault(fsc4, set()).add(sol_id)

    wanted = set()
    for chunk in _chunked(sols_by_nsn, IN_CHUNK):
        for supplier_id, nsn in QuoteSupplierNSN.objects.filter(nsn__in=chunk).values_list(
            'supplier_id', 'nsn'
        ):
            for sol_id in sols_by_nsn[nsn]:
                wanted.add((sol_id, supplier_id, QuoteSolicitationMatch.SOURCE_NSN))
    for chunk in _chunked(sols_by_fsc, IN_CHUNK):
        for supplier_id, fsc in QuoteSupplierFSC.objects.filter(fsc__in=chunk).values_list(
            'supplier_id', 'fsc'
        ):
            for sol_id in sols_by_fsc[fsc]:
                wanted.add((sol_id, supplier_id, QuoteSolicitationMatch.SOURCE_FSC))

    matched_sol_ids = {sol_id for sol_id, _, _ in wanted}
    existing = set()
    for chunk in _chunked(matched_sol_ids, IN_CHUNK):
        existing.update(
            QuoteSolicitationMatch.objects.filter(solicitation_id__in=chunk)
            .values_list('solicitation_id', 'supplier_id', 'source')
        )

    new_rows = [
        QuoteSolicitationMatch(solicitation_id=s, supplier_id=sup, source=src)
        for s, sup, src in sorted(wanted - existing)
    ]
    promoted = 0
    with transaction.atomic():
        for chunk in _chunked(new_rows, INSERT_CHUNK):
            QuoteSolicitationMatch.objects.bulk_create(chunk)
        for chunk in _chunked(matched_sol_ids, IN_CHUNK):
            promoted += QuoteSolicitation.objects.filter(
                solicitation_id__in=chunk,
                status=QuoteSolicitation.STATUS_UNMATCHED,
            ).update(
                status=QuoteSolicitation.STATUS_MATCHED,
                status_changed_at=timezone.now(),
            )

    return {
        'lines_scanned': len(lines),
        'matches_created': len(new_rows),
        'solicitations_matched': len(matched_sol_ids),
        'promoted_to_matched': promoted,
    }


def process_import_batch(batch) -> dict:
    """Seed workflow state and run matching for every solicitation in a batch."""
    sol_ids = list(
        Solicitation.objects.filter(import_batch=batch).values_list('pk', flat=True)
    )
    seeded = seed_solicitation_states(sol_ids)
    summary = match_solicitations(sol_ids)
    summary['states_seeded'] = seeded
    logger.info('quote matching for import batch %s: %s', batch.pk, summary)
    return summary
