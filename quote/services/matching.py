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


def _index_lines(solicitation_ids):
    """
    Lines of the given solicitations, indexed for matching:
    ``(lines, {nsn13: {sol_id}}, {fsc4: {sol_id}})``.
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
    return lines, sols_by_nsn, sols_by_fsc


def _wanted_matches(sols_by_nsn, sols_by_fsc, nsn_pairs=None, fsc_pairs=None):
    """
    The ``(sol_id, supplier_id, source)`` links the capability rows call for.

    Reads the capability tables unless explicit ``(supplier_id, key)`` pairs are
    passed -- that is what lets a dry run ask "what if these were added?"
    through exactly the code that does the real matching.
    """
    if nsn_pairs is None:
        nsn_pairs = set()
        for chunk in _chunked(sols_by_nsn, IN_CHUNK):
            nsn_pairs.update(
                QuoteSupplierNSN.objects.filter(nsn__in=chunk).values_list('supplier_id', 'nsn')
            )
    if fsc_pairs is None:
        fsc_pairs = set()
        for chunk in _chunked(sols_by_fsc, IN_CHUNK):
            fsc_pairs.update(
                QuoteSupplierFSC.objects.filter(fsc__in=chunk).values_list('supplier_id', 'fsc')
            )

    wanted = set()
    for supplier_id, nsn in nsn_pairs:
        for sol_id in sols_by_nsn.get(nsn, ()):
            wanted.add((sol_id, supplier_id, QuoteSolicitationMatch.SOURCE_NSN))
    for supplier_id, fsc in fsc_pairs:
        for sol_id in sols_by_fsc.get(fsc, ()):
            wanted.add((sol_id, supplier_id, QuoteSolicitationMatch.SOURCE_FSC))
    return wanted


def _existing_matches(solicitation_ids):
    """``{(sol_id, supplier_id, source)}`` already recorded for these solicitations."""
    existing = set()
    for chunk in _chunked(solicitation_ids, IN_CHUNK):
        existing.update(
            QuoteSolicitationMatch.objects.filter(solicitation_id__in=chunk)
            .values_list('solicitation_id', 'supplier_id', 'source')
        )
    return existing


def preview_matches(solicitation_ids, nsn_pairs=(), fsc_pairs=()) -> dict:
    """
    Dry run: what would adding these ``(supplier_id, nsn13)`` / ``(supplier_id,
    fsc4)`` capability pairs do to the given solicitations? Writes nothing.

    ``new_links`` are supplier links that don't exist yet, ``solicitations`` the
    distinct solicitations that would gain one, and ``newly_matched`` how many of
    those are UNMATCHED today (they would move to MATCHED).
    """
    _, sols_by_nsn, sols_by_fsc = _index_lines(solicitation_ids)
    wanted = _wanted_matches(sols_by_nsn, sols_by_fsc, set(nsn_pairs), set(fsc_pairs))
    fresh = wanted - _existing_matches({sol_id for sol_id, _, _ in wanted})
    fresh_sols = {sol_id for sol_id, _, _ in fresh}
    newly_matched = 0
    for chunk in _chunked(fresh_sols, IN_CHUNK):
        newly_matched += QuoteSolicitation.objects.filter(
            solicitation_id__in=chunk, status=QuoteSolicitation.STATUS_UNMATCHED,
        ).count()
    return {
        'new_links': len(fresh),
        'solicitations': len(fresh_sols),
        'newly_matched': newly_matched,
    }


def match_solicitations(solicitation_ids) -> dict:
    """
    Link suppliers to the given solicitations by NSN and FSC capability, then
    move UNMATCHED solicitations that gained a supplier to MATCHED.
    """
    lines, sols_by_nsn, sols_by_fsc = _index_lines(solicitation_ids)
    wanted = _wanted_matches(sols_by_nsn, sols_by_fsc)

    matched_sol_ids = {sol_id for sol_id, _, _ in wanted}
    existing = _existing_matches(matched_sol_ids)

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


# ── Manual matching + capability learning (Phase 1 feedback loop) ────────────

def _line_keys(solicitation):
    """13-digit NSNs and 4-char FSCs across a solicitation's lines."""
    nsns, fscs = set(), set()
    for nsn, fsc in solicitation.lines.values_list('nsn', 'fsc'):
        nsn13 = normalize_nsn(nsn)
        if nsn13:
            nsns.add(nsn13)
        fsc4 = (fsc or nsn13[:4] or '').strip()
        if len(fsc4) == 4:
            fscs.add(fsc4)
    return nsns, fscs


def open_matchable_ids(nsns=None, fscs=None):
    """
    Ids of open solicitations still in a matching state. When ``nsns`` / ``fscs``
    are given, only those with a line on one of them.

    SolicitationLine.nsn is stored hyphenated, so NSN candidates are narrowed by
    FSC (the first four digits, an indexed column) and confirmed in Python.
    """
    today = timezone.now().date()
    matchable = QuoteSolicitation.objects.filter(
        status__in=QuoteSolicitation.MATCHING_STATES,
        solicitation__return_by_date__gte=today,
    ).values('solicitation_id')
    if nsns is None and fscs is None:
        return set(matchable.values_list('solicitation_id', flat=True))

    nsns = set(nsns or ())
    fscs = set(fscs or ())
    lines = SolicitationLine.objects.filter(solicitation_id__in=matchable)
    sol_ids = set()
    for chunk in _chunked({n[:4] for n in nsns}, IN_CHUNK):
        for sol_id, nsn in lines.filter(fsc__in=chunk).values_list('solicitation_id', 'nsn'):
            if normalize_nsn(nsn) in nsns:
                sol_ids.add(sol_id)
    for chunk in _chunked(fscs, IN_CHUNK):
        sol_ids.update(lines.filter(fsc__in=chunk).values_list('solicitation_id', flat=True))
    return sol_ids


def add_manual_match(solicitation, supplier, user, save_nsn=False, save_fsc=False):
    """
    Link a supplier to a solicitation by hand (Quote.md "Manual Matching &
    Feedback Loop"). Optionally teach the capability tables so future imports
    match automatically, and immediately re-match other open solicitations
    that share those NSNs / FSCs.
    """
    nsns, fscs = _line_keys(solicitation)
    with transaction.atomic():
        QuoteSolicitationMatch.objects.get_or_create(
            solicitation=solicitation, supplier=supplier,
            source=QuoteSolicitationMatch.SOURCE_MANUAL,
            defaults={'matched_by': user},
        )
        state, _ = QuoteSolicitation.objects.get_or_create(solicitation=solicitation)
        if state.status == QuoteSolicitation.STATUS_UNMATCHED:
            state.set_status(QuoteSolicitation.STATUS_MATCHED)
            state.save(update_fields=['status', 'status_changed_at', 'modified_on'])
        learned_nsns = set()
        if save_nsn:
            for nsn in nsns:
                _, created = QuoteSupplierNSN.objects.get_or_create(
                    supplier=supplier, nsn=nsn, defaults={'added_by': user},
                )
                if created:
                    learned_nsns.add(nsn)
        learned_fscs = set()
        if save_fsc:
            for fsc in fscs:
                _, created = QuoteSupplierFSC.objects.get_or_create(
                    supplier=supplier, fsc=fsc, defaults={'added_by': user},
                )
                if created:
                    learned_fscs.add(fsc)

    rematched = {}
    if learned_nsns or learned_fscs:
        ids = open_matchable_ids(nsns=learned_nsns, fscs=learned_fscs)
        ids.discard(solicitation.pk)
        if ids:
            rematched = match_solicitations(sorted(ids))
    return {
        'learned_nsns': sorted(learned_nsns),
        'learned_fscs': sorted(learned_fscs),
        'rematched': rematched,
    }


def remove_manual_match(solicitation, supplier):
    """Drop a manual link; fall back to UNMATCHED when no supplier is left."""
    with transaction.atomic():
        QuoteSolicitationMatch.objects.filter(
            solicitation=solicitation, supplier=supplier,
            source=QuoteSolicitationMatch.SOURCE_MANUAL,
        ).delete()
        state = QuoteSolicitation.objects.filter(solicitation=solicitation).first()
        if (
            state
            and state.status == QuoteSolicitation.STATUS_MATCHED
            and not QuoteSolicitationMatch.objects.filter(solicitation=solicitation).exists()
        ):
            state.set_status(QuoteSolicitation.STATUS_UNMATCHED)
            state.save(update_fields=['status', 'status_changed_at', 'modified_on'])


def prune_derived_matches(removed) -> dict:
    """
    After capabilities are deleted, drop the NSN / FSC links nothing supports any
    more, and send solicitations left with no supplier back to UNMATCHED.

    ``removed`` is ``{supplier_id: (nsns, fscs)}`` -- what was just deleted.
    Only open solicitations still in a matching state are touched, and only
    links of the affected suppliers: a solicitation somebody already worked
    (RFQ sent, quoting, bid...) keeps its history, and manual links always stay.
    """
    all_nsns = set().union(*(nsns for nsns, _ in removed.values())) if removed else set()
    all_fscs = set().union(*(fscs for _, fscs in removed.values())) if removed else set()
    sol_ids = open_matchable_ids(nsns=all_nsns, fscs=all_fscs)
    if not sol_ids:
        return {'matches_removed': 0, 'returned_to_unmatched': 0}

    _, sols_by_nsn, sols_by_fsc = _index_lines(sorted(sol_ids))
    wanted = _wanted_matches(sols_by_nsn, sols_by_fsc)   # what the tables still call for

    stale_pks, touched = [], set()
    for chunk in _chunked(sol_ids, IN_CHUNK):
        for pk, sol_id, supplier_id, source in QuoteSolicitationMatch.objects.filter(
            solicitation_id__in=chunk,
            supplier_id__in=list(removed),
            source__in=[QuoteSolicitationMatch.SOURCE_NSN, QuoteSolicitationMatch.SOURCE_FSC],
        ).values_list('pk', 'solicitation_id', 'supplier_id', 'source'):
            if (sol_id, supplier_id, source) not in wanted:
                stale_pks.append(pk)
                touched.add(sol_id)

    returned = 0
    with transaction.atomic():
        for chunk in _chunked(stale_pks, IN_CHUNK):
            QuoteSolicitationMatch.objects.filter(pk__in=chunk).delete()
        for chunk in _chunked(touched, IN_CHUNK):
            still_linked = set(
                QuoteSolicitationMatch.objects.filter(solicitation_id__in=chunk)
                .values_list('solicitation_id', flat=True)
            )
            orphaned = [sol_id for sol_id in chunk if sol_id not in still_linked]
            if orphaned:
                returned += QuoteSolicitation.objects.filter(
                    solicitation_id__in=orphaned, status=QuoteSolicitation.STATUS_MATCHED,
                ).update(
                    status=QuoteSolicitation.STATUS_UNMATCHED,
                    status_changed_at=timezone.now(),
                )
    return {'matches_removed': len(stale_pks), 'returned_to_unmatched': returned}


def rematch_open_solicitations():
    """Re-run NSN/FSC matching over every open solicitation still in a matching state."""
    ids = sorted(open_matchable_ids())
    summary = match_solicitations(ids)
    summary['solicitations_scanned'] = len(ids)
    return summary
