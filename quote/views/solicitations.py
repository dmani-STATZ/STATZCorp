"""
Phase 1 screens: the solicitation queue and the per-solicitation workspace.

Views orchestrate only -- matching, queueing and claims live in quote/services
and on the models.
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_GET, require_POST

from dibbs.models import ApprovedSource, NsnProcurementHistory, Solicitation
from quote.models import QuoteRFQ, QuoteSolicitation, QuoteSolicitationMatch
from quote.services.matching import (
    add_manual_match,
    normalize_nsn,
    rematch_open_solicitations,
    remove_manual_match,
    seed_solicitation_states,
)
from quote.services.queue import SET_ASIDE_LABELS, build_queue_rows, queue_delta, status_counts
from quote.services.rfq import queue_rfqs
from quote.services.walk import claim_next
from suppliers.models import Supplier

SUPPLIER_SEARCH_LIMIT = 25
PROCUREMENT_HISTORY_LIMIT = 10


def _state_for(solicitation):
    """The solicitation's workflow row, seeding it if the import signal missed it."""
    state = QuoteSolicitation.objects.filter(solicitation=solicitation).select_related(
        'claimed_by'
    ).first()
    if state is None:
        seed_solicitation_states([solicitation.pk])
        state = QuoteSolicitation.objects.select_related('claimed_by').get(
            solicitation=solicitation
        )
    return state


def _workspace_url(solicitation):
    return reverse('quote:solicitation_workspace', args=[solicitation.solicitation_number])


def _is_xhr(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _done(request, solicitation, ok=True, status=200):
    """
    Finish a workspace POST. Fetch callers (the "& next" buttons) get JSON so
    the browser can move straight on; Django messages stay in the session and
    appear on the next full page. Plain form posts redirect back as before.
    """
    if _is_xhr(request):
        return JsonResponse({'ok': ok}, status=status)
    return redirect(_workspace_url(solicitation))


# ── Queue ────────────────────────────────────────────────────────────────────

@login_required
def solicitation_queue(request):
    """GET /quote/solicitations/ -- shell; rows load from queue_data."""
    return render(request, 'quote/solicitations/queue.html', {
        'section': 'solicitations',
        'counts': status_counts(),
        'set_aside_labels': SET_ASIDE_LABELS,
        'initial_tab': request.GET.get('tab', QuoteSolicitation.STATUS_UNMATCHED),
    })


#: Column order for the compact queue payload; the page rebuilds objects from it.
QUEUE_COLUMNS = (
    'id', 'sol', 'status', 'setAside', 'due', 'daysLeft', 'nsn', 'nomen', 'qty', 'uoi',
    'lines', 'estValue', 'matches', 'rfqQueued', 'rfqSent', 'claimedBy', 'claimedById',
)


@login_required
@require_GET
@gzip_page
def queue_data(request):
    """
    GET /quote/solicitations/data/ -- every open solicitation, columnar + gzipped
    (~11k rows; object-per-row JSON was ~3.7 MB).
    """
    rows = [
        [
            [r['matches']['NSN'], r['matches']['FSC'], r['matches']['MANUAL']]
            if col == 'matches' else r[col]
            for col in QUEUE_COLUMNS
        ]
        for r in build_queue_rows()
    ]
    return JsonResponse({
        'cols': QUEUE_COLUMNS,
        'rows': rows,
        'counts': status_counts(),
        'now': timezone.now().isoformat(),
        'me': request.user.pk,
    })


@login_required
@require_GET
def queue_poll(request):
    """GET /quote/solicitations/poll/?since=<iso> -- status moves + live claims."""
    since = parse_datetime(request.GET.get('since') or '')
    if since is None:
        since = timezone.now()
    elif timezone.is_naive(since):
        since = timezone.make_aware(since)
    return JsonResponse(queue_delta(since))


@login_required
@require_POST
def rerun_matching(request):
    """POST -- re-run NSN/FSC matching across every open, unworked solicitation."""
    summary = rematch_open_solicitations()
    messages.success(
        request,
        f"Matching re-run over {summary['solicitations_scanned']:,} open solicitations: "
        f"{summary['matches_created']:,} new supplier links, "
        f"{summary['promoted_to_matched']:,} moved to Matched.",
    )
    return redirect('quote:solicitation_queue')


# ── Workspace ────────────────────────────────────────────────────────────────

@login_required
def solicitation_workspace(request, sol_number):
    """GET /quote/solicitations/<sol>/ -- review, match suppliers, queue RFQs."""
    solicitation = get_object_or_404(
        Solicitation.objects.select_related('import_batch'), solicitation_number=sol_number,
    )
    state = _state_for(solicitation)
    claimed_by_other = not state.try_claim(request.user)

    lines = list(solicitation.lines.order_by('line_number', 'pk'))
    nsn13s = {normalize_nsn(line.nsn) for line in lines} - {''}
    nsn_forms = nsn13s | {line.nsn for line in lines if line.nsn}

    # Suppliers linked to this solicitation, one card each with every lineage badge.
    suppliers = {}
    for match in (
        QuoteSolicitationMatch.objects.filter(solicitation=solicitation)
        .select_related('supplier', 'matched_by').order_by('supplier__name', 'source')
    ):
        entry = suppliers.setdefault(match.supplier_id, {
            'supplier': match.supplier, 'sources': [], 'manual': False, 'rfqs': [],
        })
        entry['sources'].append(match.source)
        entry['manual'] = entry['manual'] or match.source == QuoteSolicitationMatch.SOURCE_MANUAL
    for rfq in QuoteRFQ.objects.filter(line__solicitation=solicitation).select_related('supplier'):
        entry = suppliers.setdefault(rfq.supplier_id, {
            'supplier': rfq.supplier, 'sources': [], 'manual': False, 'rfqs': [],
        })
        entry['rfqs'].append(rfq)
    for entry in suppliers.values():
        statuses = {r.status for r in entry['rfqs']}
        entry['rfq_status'] = (
            'SENT' if statuses & {QuoteRFQ.STATUS_SENT, QuoteRFQ.STATUS_RESPONDED}
            else 'QUEUED' if statuses & {QuoteRFQ.STATUS_QUEUED, QuoteRFQ.STATUS_READY_TO_SEND}
            else ''
        )

    # Approved sources (AS file) -- de-duplicated across daily batches, with the
    # supplier record when the CAGE is already in our directory.
    approved = list(
        ApprovedSource.objects.filter(nsn__in=nsn_forms)
        .values('nsn', 'approved_cage', 'part_number', 'company_name')
        .order_by('approved_cage', 'part_number').distinct()
    )
    cage_to_supplier = {}
    cages = {a['approved_cage'] for a in approved if a['approved_cage']}
    if cages:
        for supplier in Supplier.objects.filter(cage_code__in=cages, archived=False):
            cage_to_supplier.setdefault((supplier.cage_code or '').upper(), supplier)
    for a in approved:
        a['supplier'] = cage_to_supplier.get((a['approved_cage'] or '').upper())
        a['linked'] = bool(a['supplier'] and a['supplier'].pk in suppliers)

    return render(request, 'quote/solicitations/workspace.html', {
        'section': 'solicitations',
        'solicitation': solicitation,
        'state': state,
        'claimed_by_other': claimed_by_other,
        'lines': lines,
        'suppliers': list(suppliers.values()),
        'approved_sources': approved,
        'procurement_history': NsnProcurementHistory.objects.filter(nsn__in=nsn13s)
        .order_by('-award_date')[:PROCUREMENT_HISTORY_LIMIT],
        'set_aside_label': SET_ASIDE_LABELS.get(solicitation.small_business_set_aside or '', ''),
        'days_left': (
            (solicitation.return_by_date - timezone.now().date()).days
            if solicitation.return_by_date else None
        ),
        'can_match': state.status in QuoteSolicitation.MATCHING_STATES,
    })


@login_required
@require_GET
def supplier_search(request):
    """GET /quote/suppliers/search/?q= -- name / CAGE / supplier-type lookup (JSON)."""
    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    qs = (
        Supplier.objects.filter(archived=False)
        .filter(
            Q(name__icontains=q)
            | Q(cage_code__iexact=q)
            | Q(supplier_type__description__icontains=q)
        )
        .select_related('supplier_type')
        .order_by('name')[:SUPPLIER_SEARCH_LIMIT]
    )
    return JsonResponse({'results': [
        {
            'id': s.pk,
            'name': s.name or '(no name)',
            'cage': s.cage_code or '',
            'type': s.supplier_type.description if s.supplier_type else '',
            'packhouse': bool(s.is_packhouse),
        }
        for s in qs
    ]})


def _solicitation_or_404(sol_number):
    return get_object_or_404(Solicitation, solicitation_number=sol_number)


@login_required
@require_POST
def add_match(request, sol_number):
    """POST -- manually link a supplier; optionally teach NSN / FSC capability."""
    solicitation = _solicitation_or_404(sol_number)
    supplier = get_object_or_404(Supplier, pk=request.POST.get('supplier_id'))
    result = add_manual_match(
        solicitation, supplier, request.user,
        save_nsn=request.POST.get('save_nsn') == 'on',
        save_fsc=request.POST.get('save_fsc') == 'on',
    )
    note = f'{supplier.name} linked.'
    learned = result['learned_nsns'] + result['learned_fscs']
    if learned:
        note += f" Saved {', '.join(learned)} to the supplier for future runs."
    promoted = (result['rematched'] or {}).get('promoted_to_matched', 0)
    if promoted:
        note += f' {promoted} other open solicitation(s) matched automatically.'
    messages.success(request, note)
    return redirect(_workspace_url(solicitation))


@login_required
@require_POST
def remove_match(request, sol_number, supplier_id):
    """POST -- drop a manual link."""
    solicitation = _solicitation_or_404(sol_number)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    remove_manual_match(solicitation, supplier)
    messages.info(request, f'Manual link to {supplier.name} removed.')
    return redirect(_workspace_url(solicitation))


@login_required
@require_POST
def queue_supplier_rfqs(request, sol_number):
    """POST supplier_ids[] -- queue RFQs for the chosen suppliers."""
    solicitation = _solicitation_or_404(sol_number)
    ids = [i for i in request.POST.getlist('supplier_ids') if i.isdigit()]
    suppliers = list(Supplier.objects.filter(pk__in=ids))
    if not suppliers:
        messages.warning(request, 'Pick at least one supplier to queue.')
        return _done(request, solicitation, ok=False, status=400)
    created = queue_rfqs(solicitation, suppliers, request.user)
    messages.success(
        request,
        f'{sol_number}: {created} RFQ line(s) queued for {len(suppliers)} supplier(s). '
        'Send them from the RFQ Queue.',
    )
    return _done(request, solicitation)


@login_required
@require_POST
def set_status(request, sol_number):
    """POST action=no_bid|reopen -- pass on a solicitation or bring it back."""
    solicitation = _solicitation_or_404(sol_number)
    state = _state_for(solicitation)
    action = request.POST.get('action')
    if action == 'no_bid':
        state.set_status(QuoteSolicitation.STATUS_NO_BID)
        messages.info(request, f'{sol_number} marked No Bid.')
    elif action == 'reopen':
        has_match = QuoteSolicitationMatch.objects.filter(solicitation=solicitation).exists()
        state.set_status(
            QuoteSolicitation.STATUS_MATCHED if has_match else QuoteSolicitation.STATUS_UNMATCHED
        )
        messages.info(request, f'{sol_number} reopened.')
    else:
        messages.error(request, 'Unknown action.')
        return _done(request, solicitation, ok=False, status=400)
    state.save(update_fields=['status', 'status_changed_at', 'modified_on'])
    return _done(request, solicitation)


@login_required
@require_POST
def claim(request, sol_number):
    """
    POST action=take|release|renew.

    * take    -- take over from another rep (explicit, unconditional).
    * release -- drop your claim and return to the queue.
    * renew   -- heartbeat from an open workspace; JSON says whether you still
                 hold it (someone may have taken over).
    """
    state = _state_for(_solicitation_or_404(sol_number))
    action = request.POST.get('action')
    if action == 'renew':
        held = state.try_claim(request.user)
        holder = state.claimed_by
        return JsonResponse({
            'held': held,
            'by': '' if held or holder is None else (holder.get_full_name() or holder.username),
            'expires': state.claim_expires_at.isoformat() if state.claim_expires_at else None,
        })
    if action == 'release':
        state.release_claim(request.user)
        if _is_xhr(request):
            return JsonResponse({'ok': True})
        return redirect('quote:solicitation_queue')
    state.claim_for(request.user)
    messages.info(request, 'You now hold the review claim.')
    return redirect(_workspace_url(state.solicitation))


@login_required
@require_POST
def walk_next(request):
    """
    POST JSON {candidates: [sol numbers], status, release} -- claim the next
    solicitation in the rep's list that is still ``status`` and not held by a
    teammate. Returns {sol, url, skipped: [{sol, reason}]}.
    """
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'Bad JSON.'}, status=400)
    candidates = [str(c) for c in payload.get('candidates') or [] if c]
    status = payload.get('status') or ''
    if status and status not in dict(QuoteSolicitation.STATUS_CHOICES):
        return JsonResponse({'error': 'Unknown status.'}, status=400)
    result = claim_next(request.user, candidates, status, release=payload.get('release'))
    result['url'] = (
        reverse('quote:solicitation_workspace', args=[result['sol']]) if result['sol'] else None
    )
    return JsonResponse(result)
