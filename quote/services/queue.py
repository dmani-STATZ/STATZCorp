"""
Solicitation queue dataset for the Phase 1 matching screens.

The queue page loads every open solicitation in one compact JSON payload and
filters client-side (Quote.md Phase 1: "snappy client-side dataset ... without
round-trip database reloads"). A handful of set-based queries build it:

  1. open QuoteSolicitation rows (+ solicitation fields, never the PDF blob)
  2. their lines
  3. the latest DLA unit cost per NSN (chunked ``nsn__in`` index seeks)
  4. match counts per (solicitation, source)
  5. queued / sent RFQ counts per solicitation

Lookups keyed on the open set are subqueries on the same filter; the NSN
lookup is chunked under SQL Server's 2,100-parameter limit.

Performance notes (dev, ~11k open solicitations, ~3s total):
  * ``select_related('solicitation')`` without ``only()`` drags every stored
    PDF blob across the wire -- ~15s by itself.
  * A correlated "latest unit cost" subquery per line ran ~0.4s per row on
    SQL Server; the chunked lookup does all NSNs in ~2s.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from dibbs.models import NsnProcurementHistory, SolicitationLine
from quote.models import QuoteRFQ, QuoteSolicitation, QuoteSolicitationMatch

#: Statuses the Phase 1 queue shows, in tab order.
QUEUE_STATUSES = (
    QuoteSolicitation.STATUS_UNMATCHED,
    QuoteSolicitation.STATUS_MATCHED,
    QuoteSolicitation.STATUS_RFQ_SENT,
)

NSN_CHUNK = 1000

SET_ASIDE_LABELS = {
    'N': 'Unrestricted',
    'Y': 'Small Business',
    'H': 'HUBZone',
    'R': 'SDVOSB',
    'L': 'WOSB',
    'A': '8(a)',
    'E': 'EDWOSB',
}


def _open_states(today):
    return QuoteSolicitation.objects.filter(
        status__in=QUEUE_STATUSES,
        solicitation__return_by_date__gte=today,
    )


def latest_unit_costs(nsns):
    """{13-digit NSN: most recent DLA-paid unit cost} for the given NSNs."""
    nsns = sorted(nsns)
    latest = {}
    for start in range(0, len(nsns), NSN_CHUNK):
        for nsn, cost, awarded in NsnProcurementHistory.objects.filter(
            nsn__in=nsns[start:start + NSN_CHUNK],
        ).values_list('nsn', 'unit_cost', 'award_date'):
            if nsn not in latest or awarded > latest[nsn][1]:
                latest[nsn] = (cost, awarded)
    return {nsn: cost for nsn, (cost, _) in latest.items()}


def build_queue_rows(today=None):
    """Return the list of row dicts the queue page renders client-side."""
    today = today or timezone.now().date()
    now = timezone.now()
    states = _open_states(today)
    open_sol_ids = states.values('solicitation_id')

    rows = {}
    for state in states.select_related('solicitation', 'claimed_by').only(
        'status', 'claimed_by_id', 'claim_expires_at', 'solicitation_id',
        'solicitation__solicitation_number', 'solicitation__small_business_set_aside',
        'solicitation__return_by_date',
        'claimed_by__username', 'claimed_by__first_name', 'claimed_by__last_name',
    ).order_by(
        'solicitation__return_by_date', 'solicitation__solicitation_number',
    ):
        sol = state.solicitation
        claimed = (
            state.claimed_by_id and state.claim_expires_at and state.claim_expires_at >= now
        )
        rows[sol.pk] = {
            'id': sol.pk,
            'sol': sol.solicitation_number,
            'status': state.status,
            'setAside': sol.small_business_set_aside or '',
            'due': sol.return_by_date.isoformat() if sol.return_by_date else '',
            'daysLeft': (sol.return_by_date - today).days if sol.return_by_date else None,
            'nsn': '',
            'nomen': '',
            'qty': None,
            'uoi': '',
            'lines': 0,
            'estValue': None,
            'matches': {'NSN': 0, 'FSC': 0, 'MANUAL': 0},
            'rfqQueued': 0,
            'rfqSent': 0,
            'claimedBy': (
                (state.claimed_by.get_full_name() or state.claimed_by.username)
                if claimed else ''
            ),
            'claimedById': state.claimed_by_id if claimed else None,
        }

    lines = list(
        SolicitationLine.objects.filter(solicitation_id__in=open_sol_ids)
        .order_by('solicitation_id', 'line_number', 'pk')
        .values_list('solicitation_id', 'nsn', 'nomenclature', 'quantity', 'unit_of_issue')
    )
    costs = latest_unit_costs({
        (nsn or '').replace('-', '') for _, nsn, _, _, _ in lines
        if len((nsn or '').replace('-', '')) == 13
    })
    est = defaultdict(Decimal)
    est_known = set()
    for sol_id, nsn, nomen, qty, uoi in lines:
        last_cost = costs.get((nsn or '').replace('-', ''))
        row = rows.get(sol_id)
        if row is None:
            continue
        if row['lines'] == 0:
            row.update(nsn=nsn or '', nomen=nomen or '', qty=qty, uoi=uoi or '')
        row['lines'] += 1
        if last_cost is not None and qty:
            est[sol_id] += Decimal(last_cost) * qty
            est_known.add(sol_id)
    for sol_id in est_known:
        rows[sol_id]['estValue'] = float(round(est[sol_id], 2))

    for sol_id, source, n in (
        QuoteSolicitationMatch.objects.filter(solicitation_id__in=open_sol_ids)
        .values_list('solicitation_id', 'source')
        .annotate(n=Count('id'))
        .order_by()
    ):
        if sol_id in rows:
            rows[sol_id]['matches'][source] = n

    for sol_id, queued, sent in (
        QuoteRFQ.objects.filter(line__solicitation_id__in=open_sol_ids)
        .values_list('line__solicitation_id')
        .annotate(
            queued=Count('id', filter=Q(status__in=[
                QuoteRFQ.STATUS_QUEUED, QuoteRFQ.STATUS_READY_TO_SEND,
            ])),
            sent=Count('id', filter=Q(status__in=[
                QuoteRFQ.STATUS_SENT, QuoteRFQ.STATUS_RESPONDED,
            ])),
        )
        .order_by()
    ):
        if sol_id in rows:
            rows[sol_id]['rfqQueued'] = queued
            rows[sol_id]['rfqSent'] = sent

    return list(rows.values())


def status_counts(today=None):
    """Open-solicitation counts per queue status (for tabs and the dashboard)."""
    today = today or timezone.now().date()
    counts = dict(
        _open_states(today).values_list('status').annotate(n=Count('id')).order_by()
    )
    return {status: counts.get(status, 0) for status in QUEUE_STATUSES}


def queue_delta(since, today=None):
    """
    What changed since ``since`` (an aware datetime): status moves and the
    current claim map. Drives the queue page's self-scheduling poll.
    """
    today = today or timezone.now().date()
    now = timezone.now()
    changed = list(
        QuoteSolicitation.objects.filter(
            status_changed_at__gt=since, solicitation__return_by_date__gte=today,
        ).values_list('solicitation_id', 'status')
    )
    claims = {}
    for sol_id, user_id, first, last, username in (
        QuoteSolicitation.objects.filter(
            claimed_by__isnull=False,
            claim_expires_at__gte=now,
            solicitation__return_by_date__gte=today,
        ).values_list(
            'solicitation_id', 'claimed_by_id', 'claimed_by__first_name',
            'claimed_by__last_name', 'claimed_by__username',
        )
    ):
        name = f'{first} {last}'.strip() or username
        claims[sol_id] = {'userId': user_id, 'name': name}
    return {
        'changed': [{'id': sol_id, 'status': status} for sol_id, status in changed],
        'claims': claims,
        'now': now.isoformat(),
    }
