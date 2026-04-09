"""
Solicitation list and detail views.
"""
import json
import urllib.parse
from datetime import date, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import (
    Count,
    Exists,
    F,
    IntegerField,
    Prefetch,
    Q,
    OuterRef,
    Subquery,
    Max,
    Value,
)
from django.db.models.functions import Coalesce, Replace
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages

from sales.models import (
    Solicitation,
    SolicitationLine,
    ImportBatch,
    ApprovedSource,
    SupplierMatch,
    SupplierRFQ,
    SupplierQuote,
    SupplierContactLog,
    CompanyCAGE,
    GovernmentBid,
    DibbsAward,
    WeWonAward,
    NsnProcurementHistory,
    SolPackaging,
    MassPassLog,
    SavedFilter,
    SolicitationMatchCount,
    SAMEntityCache,
)
from sales.services.matching import _normalize_nsn, get_live_workbench_matches
from sales.services.no_quote import get_no_quote_cage_set, normalize_cage_code
from suppliers.models import Supplier

# Cost of money daily rate — assumed 12% annually (0.12 / 365)
# UPDATE THIS VALUE once confirmed with management.
# 0.000329 = ~12% annual. Do NOT use 0.00075 (that implies ~27% annual).
COST_OF_MONEY_DAILY_RATE = 0.000329

PIPELINE = [
    ("New", "📥", "New"),
    ("Active", "📌", "Active"),
    ("Matching", "🎯", "Matching"),
    ("RFQ_PENDING", "📋", "RFQ Pending"),
    ("RFQ_SENT", "📨", "RFQ Sent"),
    ("QUOTING", "💬", "Quoting"),
    ("BID_READY", "💰", "Bid Ready"),
    ("BID_SUBMITTED", "⬆", "Submitted"),
]
STATUS_ORDER = [s[0] for s in PIPELINE]


def _build_pipeline_steps(current_status):
    try:
        current_idx = STATUS_ORDER.index(current_status)
    except ValueError:
        current_idx = 0
    steps = []
    for i, (status, icon, label) in enumerate(PIPELINE):
        if i < current_idx:
            state = "done"
        elif i == current_idx:
            state = "active"
        else:
            state = ""
        steps.append({"icon": icon, "label": label, "state": state})
    return steps


SET_ASIDE_CHOICES = [
    ('',  'All set-asides'),
    ('R', 'SDVOSB'),
    ('H', 'HUBZone'),
    ('Y', 'Small Business'),
    ('L', 'WOSB'),
    ('A', '8(a)'),
    ('E', 'EDWOSB'),
    ('N', 'Unrestricted'),
]

SET_ASIDE_LABELS = {v: label for v, label in SET_ASIDE_CHOICES if v}

# Values that mean "unrestricted" for tab filtering (Solicitation.small_business_set_aside).
UNRESTRICTED_CODES = ['N', '']
UNRESTRICTED_TAB_Q = (
    Q(small_business_set_aside__in=UNRESTRICTED_CODES)
    | Q(small_business_set_aside__isnull=True)
)
VALID_TABS = frozenset({
    'matches', 'set_asides', 'unrestricted', 'research', 'nobid',
    'growth', 'approved_sources',
})

# Default list view: pipeline only (excludes terminal / closed-out rows). Align with dashboard
# PIPELINE_STATUSES plus Matching (in-triage). Not applied when tab=nobid.
LIST_PIPELINE_STATUSES = [
    'New',
    'Active',
    'Matching',
    'RESEARCH',
    'RFQ_PENDING',
    'RFQ_SENT',
    'QUOTING',
    'BID_READY',
    'BID_SUBMITTED',
]

# GET keys excluded from saved-filter matching and from list_qs / filter_snapshot
_LIST_FILTER_UI_KEYS = frozenset({'page', 'active_chip'})


def _normalize_filter_params_dict(d):
    """Canonical dict for comparing saved JSON to the current query string."""
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        sk = str(k).strip()
        if not sk or sk in _LIST_FILTER_UI_KEYS:
            continue
        sv = (str(v) if v is not None else '').strip()
        if sv == '':
            continue
        out[sk] = sv
    return dict(sorted(out.items()))


def _canonical_list_filter_params_from_get(get):
    """Serialize active list filters from a QueryDict (exclude page)."""
    out = {}
    for key in get:
        if key in _LIST_FILTER_UI_KEYS:
            continue
        val = get.get(key)
        if val is None:
            continue
        s = val.strip() if isinstance(val, str) else str(val).strip()
        if s == '':
            continue
        out[key] = s
    return dict(sorted(out.items()))


def _find_matching_saved_filter_pk(saved_filters_ordered, active_canon):
    if not active_canon:
        return None
    for sf in saved_filters_ordered:
        if _normalize_filter_params_dict(sf.filter_params) == active_canon:
            return sf.pk
    return None


def _saved_filter_list_url(filter_params):
    """Build solicitation list URL from stored JSON filter_params."""
    if not isinstance(filter_params, dict):
        filter_params = {}
    pairs = []
    for k, v in sorted(filter_params.items()):
        sk = str(k).strip()
        sv = (str(v) if v is not None else '').strip()
        if not sk or not sv:
            continue
        pairs.append((sk, sv))
    q = urllib.parse.urlencode(pairs)
    base = reverse('sales:solicitation_list')
    return f'{base}?{q}' if q else base


# SQL Server IN clause parameter limit — chunk snapshot IDs on mass-pass undo
_MASS_PASS_UNDO_CHUNK = 100


def _mass_pass_chunked(lst, size=_MASS_PASS_UNDO_CHUNK):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

# Sort: valid GET values are field name (asc) or -field (desc). Third click clears (default order).
DEFAULT_ORDER = ('return_by_date', 'solicitation_number')
SORTABLE_FIELDS = frozenset({
    'solicitation_number', 'nsn', 'nomenclature', 'quantity',
    'set_aside', 'return_by_date', 'status', 'match_count',
})

# Sol Review / Research queue session routing (mirrors InboxMessage 20-minute claim pattern)
QUEUE_KIND_ACTIVE = 'active'
QUEUE_KIND_RESEARCH = 'research'


def _queue_session_keys(kind):
    if kind == QUEUE_KIND_RESEARCH:
        return 'research_queue', 'research_index'
    return 'sol_review_queue', 'sol_review_index'


def _valid_statuses_for_queue(kind):
    if kind == QUEUE_KIND_RESEARCH:
        return ['RESEARCH']
    return ['New', 'Active']


def _queue_list_redirect(kind):
    return 'sales:research_queue' if kind == QUEUE_KIND_RESEARCH else 'sales:sol_review_queue'


def _is_claimed_by_other(sol, user, now):
    if not sol.review_claim_expires_at or sol.review_claim_expires_at <= now:
        return False
    if sol.review_claimed_by_id is None:
        return False
    return sol.review_claimed_by_id != user.id


def _release_review_claim(sol):
    sol.review_claimed_by = None
    sol.review_claimed_at = None
    sol.review_claim_expires_at = None


def _infer_queue_kind(sol):
    return QUEUE_KIND_RESEARCH if sol.status == 'RESEARCH' else QUEUE_KIND_ACTIVE


def _workbench_sidebar_context(solicitation):
    """Shared context for workbench right rail (matches + manual add card)."""
    no_quote_cages = get_no_quote_cage_set()
    line = solicitation.lines.order_by("line_number", "id").first()
    live_matches = get_live_workbench_matches(line) if line else {"tier1": [], "tier2": [], "tier3": []}
    tier1_matches = live_matches["tier1"]
    tier2_matches = live_matches["tier2"]
    tier3_matches = live_matches["tier3"]
    queued_cages = set(
        normalize_cage_code(c)
        for c in SupplierRFQ.objects.filter(
            line__solicitation=solicitation,
            status="QUEUED",
        ).values_list("supplier__cage_code", flat=True)
        if normalize_cage_code(c)
    )
    unmatched_cages = []
    if line:
        norm = _normalize_nsn(line.nsn)
        if norm:
            seen = set()
            for c in ApprovedSource.objects.filter(nsn=norm).values_list(
                "approved_cage", flat=True
            ):
                cage = normalize_cage_code(c)
                if not cage or cage in seen:
                    continue
                seen.add(cage)
                if not Supplier.objects.filter(
                    cage_code__iexact=cage, archived=False
                ).exists():
                    unmatched_cages.append(cage)
    sam_cache_map = {}
    if unmatched_cages:
        for chunk in _mass_pass_chunked(unmatched_cages, 100):
            for r in SAMEntityCache.objects.filter(
                cage_code__in=chunk,
                fetch_error=False,
            ):
                sam_cache_map[r.cage_code] = r
    return {
        "solicitation": solicitation,
        "tier1_matches": tier1_matches,
        "tier2_matches": tier2_matches,
        "tier3_matches": tier3_matches,
        "queued_cages": queued_cages,
        "no_quote_cages": no_quote_cages,
        "sam_cache_map": sam_cache_map,
    }


def _apply_review_queue_optional_filters(qs, data):
    """Optional filters from GET/POST dict (set-aside, dates, search, match_exists)."""
    set_aside = (data.get('set_aside') or '').strip()
    if set_aside:
        qs = qs.filter(small_business_set_aside=set_aside)
    return_date_from = (data.get('return_date_from') or '').strip()
    return_date_to = (data.get('return_date_to') or '').strip()
    if return_date_from:
        try:
            qs = qs.filter(return_by_date__gte=date.fromisoformat(return_date_from))
        except ValueError:
            pass
    if return_date_to:
        try:
            qs = qs.filter(return_by_date__lte=date.fromisoformat(return_date_to))
        except ValueError:
            pass
    search = (data.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(solicitation_number__icontains=search)
            | Q(lines__nomenclature__icontains=search)
        ).distinct()
    match_exists = (data.get('match_exists') or '').strip()
    if match_exists == 'yes':
        qs = qs.annotate(_review_mc=Count('lines__supplier_matches', distinct=True)).filter(
            _review_mc__gt=0
        )
    elif match_exists == 'no':
        qs = qs.annotate(_review_mc=Count('lines__supplier_matches', distinct=True)).filter(
            _review_mc=0
        )
    return qs


def _review_queue_base_queryset(user, statuses, data=None):
    qs = Solicitation.objects.filter(status__in=statuses).annotate(
        match_count=Count('lines__supplier_matches', distinct=True)
    )
    if data is not None:
        qs = _apply_review_queue_optional_filters(qs, data)
    now = timezone.now()
    qs = qs.exclude(
        Q(review_claim_expires_at__gt=now)
        & ~Q(review_claimed_by=user)
        & Q(review_claimed_by__isnull=False)
    )
    return qs.order_by('return_by_date', 'solicitation_number')


def _redirect_next_in_queue(request, kind, after_index_exclusive):
    queue_key, index_key = _queue_session_keys(kind)
    queue = list(request.session.get(queue_key) or [])
    valid = _valid_statuses_for_queue(kind)
    now = timezone.now()
    start = after_index_exclusive + 1
    for idx in range(start, len(queue)):
        pk = queue[idx]
        try:
            s = Solicitation.objects.get(pk=pk)
        except Solicitation.DoesNotExist:
            continue
        if s.status not in valid:
            continue
        if _is_claimed_by_other(s, request.user, now):
            continue
        request.session[index_key] = idx
        request.session.modified = True
        return redirect(
            'sales:solicitation_detail',
            sol_number=s.solicitation_number,
        )
    request.session[index_key] = len(queue)
    request.session.modified = True
    messages.success(request, 'Queue complete. All solicitations have been reviewed.')
    return redirect(_queue_list_redirect(kind))


def _list_tab_from_params(params):
    raw = (params.get('tab') or '').strip()
    return raw if raw in VALID_TABS else ''


def _list_qs_before_tab(params):
    """
    Apply bucket / set-aside / status / item-type / search filters and live_match_count
    annotation (from dibbs_solicitation_match_counts via SolicitationMatchCount).
    Restricts to pipeline statuses by default; skips that restriction for tab=nobid.
    Does not apply tab filter (beyond pipeline scope), or column sort.
    """
    q = (params.get('q') or '').strip()
    set_aside = params.get('set_aside', '') or ''
    status = params.get('status', '') or ''
    item_type = params.get('item_type', '') or ''
    bucket = params.get('bucket', '') or ''
    tab = _list_tab_from_params(params)

    qs = (
        Solicitation.objects
        .exclude(status="Archived")
        .prefetch_related(
            Prefetch(
                'lines',
                queryset=SolicitationLine.objects.order_by('line_number', 'id'),
            )
        )
        .order_by('return_by_date', 'solicitation_number')
    )

    if tab != 'nobid':
        qs = qs.filter(status__in=LIST_PIPELINE_STATUSES)

    if bucket:
        qs = qs.filter(bucket=bucket)
    else:
        qs = qs.exclude(bucket='SKIP')
    if set_aside:
        qs = qs.filter(small_business_set_aside=set_aside)
    if status:
        qs = qs.filter(status=status)
    if item_type:
        qs = qs.filter(lines__item_type_indicator=item_type).distinct()
    if q:
        qs = qs.filter(
            Q(solicitation_number__icontains=q) |
            Q(lines__nomenclature__icontains=q)
        ).distinct()

    live_match_sq = SolicitationMatchCount.objects.filter(
        solicitation_id=OuterRef('pk')
    ).values('match_count')[:1]
    qs = qs.annotate(
        live_match_count=Coalesce(
            Subquery(live_match_sq, output_field=IntegerField()),
            Value(0),
        )
    )

    if (params.get('has_matches') or '').strip() == '1':
        qs = qs.filter(live_match_count__gt=0)
    if (params.get('has_approved_source') or '').strip() == '1':
        qs = qs.filter(
            Exists(
                SolicitationLine.objects.filter(solicitation_id=OuterRef('pk'))
                .annotate(nsn_norm=Replace(F('nsn'), Value('-'), Value('')))
                .filter(nsn_norm__in=ApprovedSource.objects.values('nsn'))
            )
        )

    return qs


def _apply_list_tab_filter(qs, tab):
    if tab == 'nobid':
        return qs.filter(status='NO_BID')
    if tab == 'research':
        return qs.filter(status='RESEARCH')
    if tab in ('matches', 'set_asides', 'unrestricted', 'growth', 'approved_sources'):
        qs = qs.exclude(status='NO_BID')
    elif tab not in ('',):
        qs = qs.exclude(status='NO_BID')
    if tab == 'matches':
        return qs.filter(live_match_count__gt=0)
    if tab == 'set_asides':
        return qs.exclude(UNRESTRICTED_TAB_Q)
    if tab == 'unrestricted':
        return qs.filter(UNRESTRICTED_TAB_Q)
    if tab == 'growth':
        return qs.filter(
            small_business_set_aside__isnull=False,
        ).exclude(
            small_business_set_aside__in=['R', 'H', '', 'N'],
        ).filter(
            Exists(SupplierMatch.objects.filter(line__solicitation_id=OuterRef('pk'))),
        )
    if tab == 'approved_sources':
        return qs.filter(
            Exists(
                SolicitationLine.objects.filter(solicitation_id=OuterRef('pk'))
                .annotate(nsn_norm=Replace(F('nsn'), Value('-'), Value('')))
                .filter(nsn_norm__in=ApprovedSource.objects.values('nsn'))
            )
        )
    return qs


@login_required
def research_pool_list(request):
    """
    Research Pool: same list UI with the Research tab selected (status=RESEARCH).
    Preserves other GET filters so list_qs / workbench prev-next stay aligned.
    """
    params = request.GET.copy()
    params['tab'] = 'research'
    return redirect(f"{reverse('sales:solicitation_list')}?{params.urlencode()}")


def _apply_list_sort(qs, sort_param):
    """Apply the same column sort as the list page (?sort= / ?sort=-)."""
    sort_param = (sort_param or '').strip()
    if sort_param.startswith('-'):
        sort_field = sort_param[1:]
        sort_desc = True
    else:
        sort_field = sort_param
        sort_desc = False
    if sort_field not in SORTABLE_FIELDS:
        return qs.order_by(*DEFAULT_ORDER)

    if sort_field in ('nsn', 'nomenclature', 'quantity'):
        first_line = (
            SolicitationLine.objects.filter(solicitation_id=OuterRef('pk'))
            .order_by('line_number', 'id')
        )
        if sort_field == 'nsn':
            qs = qs.annotate(first_nsn=Subquery(first_line.values('nsn')[:1]))
            order_field = 'first_nsn'
        elif sort_field == 'nomenclature':
            qs = qs.annotate(first_nomenclature=Subquery(first_line.values('nomenclature')[:1]))
            order_field = 'first_nomenclature'
        else:
            qs = qs.annotate(first_quantity=Subquery(first_line.values('quantity')[:1]))
            order_field = 'first_quantity'
    elif sort_field == 'set_aside':
        order_field = 'small_business_set_aside'
    elif sort_field == 'match_count':
        order_field = 'live_match_count'
    else:
        order_field = sort_field

    order_by = ('-' + order_field,) if sort_desc else (order_field,)
    return qs.order_by(*order_by)


def _build_list_queryset(params):
    """
    Reconstruct the filtered solicitation queryset from GET-like params.
    Used by solicitation_list and solicitation_workbench (prev/next nav).
    """
    tab = _list_tab_from_params(params)
    qs = _list_qs_before_tab(params)
    qs = _apply_list_tab_filter(qs, tab)
    qs = _apply_list_sort(qs, params.get('sort', '') or '')
    return qs


def _workbench_nav_from_list_qs(solicitation, list_qs_raw):
    """Prev/next sol numbers and 1-based index using list_qs + _build_list_queryset."""
    if not (list_qs_raw or '').strip():
        return None, None, None, None
    try:
        list_params = dict(
            urllib.parse.parse_qsl(list_qs_raw, keep_blank_values=True)
        )
        nav_qs = _build_list_queryset(list_params)
        sol_numbers = list(nav_qs.values_list('solicitation_number', flat=True))
        idx = sol_numbers.index(solicitation.solicitation_number)
        prev_sol = sol_numbers[idx - 1] if idx > 0 else None
        next_sol = sol_numbers[idx + 1] if idx < len(sol_numbers) - 1 else None
        return prev_sol, next_sol, idx + 1, len(sol_numbers)
    except (ValueError, Exception):
        return None, None, None, None


def _workbench_record_counter(solicitation, list_qs_raw, request):
    """Record X of Y: prefer list_qs order; else session review/research queue."""
    prev_sol, next_sol, num, total = _workbench_nav_from_list_qs(
        solicitation, list_qs_raw
    )
    if num is not None and total is not None:
        return prev_sol, next_sol, num, total
    kind = _infer_queue_kind(solicitation)
    queue_key, _ = _queue_session_keys(kind)
    queue = list(request.session.get(queue_key) or [])
    try:
        qidx = queue.index(solicitation.pk)
        def _sn(pk):
            return (
                Solicitation.objects.filter(pk=pk)
                .values_list('solicitation_number', flat=True)
                .first()
            )
        ps = _sn(queue[qidx - 1]) if qidx > 0 else None
        ns = _sn(queue[qidx + 1]) if qidx + 1 < len(queue) else None
        return ps, ns, qidx + 1, len(queue)
    except ValueError:
        return prev_sol, next_sol, 1, 1


def _capture_workbench_list_nav_snapshot(list_qs_raw, sol):
    """
    Snapshot (sol_numbers, idx) from list_qs filters before a PASS mutates status to NO_BID.
    After PASS, _build_list_queryset() often omits the current row, so post-save index fails.
    """
    enc = (list_qs_raw or "").strip()
    if not enc:
        return None
    try:
        list_params = dict(
            urllib.parse.parse_qsl(enc, keep_blank_values=True)
        )
        nav_qs = _build_list_queryset(list_params)
        sol_numbers = list(nav_qs.values_list("solicitation_number", flat=True))
        idx = sol_numbers.index(sol.solicitation_number)
        return (sol_numbers, idx)
    except (ValueError, Exception):
        return None


def _redirect_after_workbench_action(
    request,
    sol,
    list_qs_raw,
    queue_kind_before_mutate,
    *,
    list_nav_snapshot=None,
):
    """
    After research / pass / next: next item in list_qs order (skip current), else session queue.
    queue_kind_before_mutate: _infer_queue_kind(sol) before any status-changing save.
    list_nav_snapshot: optional (sol_numbers, idx) from _capture_workbench_list_nav_snapshot
    for PASS — same navigation intent as RESEARCH when list_qs is present.
    """
    enc = (list_qs_raw or "").strip()
    if enc:
        sol_numbers = None
        idx = None
        if list_nav_snapshot is not None:
            sol_numbers, idx = list_nav_snapshot
        else:
            try:
                list_params = dict(
                    urllib.parse.parse_qsl(enc, keep_blank_values=True)
                )
                nav_qs = _build_list_queryset(list_params)
                sol_numbers = list(nav_qs.values_list("solicitation_number", flat=True))
                idx = sol_numbers.index(sol.solicitation_number)
            except (ValueError, Exception):
                pass
        if sol_numbers is not None and idx is not None:
            for j in range(idx + 1, len(sol_numbers)):
                sn = sol_numbers[j]
                cand = Solicitation.objects.filter(solicitation_number=sn).first()
                if not cand:
                    continue
                q = urllib.parse.urlencode({"list_qs": enc})
                return redirect(
                    f"{reverse('sales:solicitation_detail', args=[sn])}?{q}"
                )
        q = urllib.parse.urlencode({"list_qs": enc})
        messages.success(request, "End of list for current filters.")
        return redirect(f"{reverse('sales:solicitation_list')}?{enc}")

    queue_key, _ = _queue_session_keys(queue_kind_before_mutate)
    queue = list(request.session.get(queue_key) or [])
    try:
        cur_idx = queue.index(sol.pk)
    except ValueError:
        cur_idx = -1
    return _redirect_next_in_queue(request, queue_kind_before_mutate, cur_idx)


def _workbench_post_action(request, sol, action, list_qs_raw):
    queue_kind = _infer_queue_kind(sol)
    now = timezone.now()

    if action == 'research':
        sol.status = 'RESEARCH'
        sol.research_flagged_by = request.user
        sol.research_flagged_at = now
        _release_review_claim(sol)
        sol.save(update_fields=[
            'status', 'research_flagged_by', 'research_flagged_at',
            'review_claimed_by', 'review_claimed_at', 'review_claim_expires_at',
        ])
        return _redirect_after_workbench_action(request, sol, list_qs_raw, queue_kind)

    if action == 'pass':
        if SupplierRFQ.objects.filter(
            line__solicitation=sol,
            status='QUEUED',
        ).exists():
            messages.error(
                request,
                'Cannot pass — RFQs already queued for this solicitation.',
            )
            q = urllib.parse.urlencode({'list_qs': list_qs_raw}) if list_qs_raw else ''
            url = reverse(
                'sales:solicitation_detail',
                args=[sol.solicitation_number],
            )
            return redirect(f'{url}?{q}' if q else url)
        list_nav_snapshot = _capture_workbench_list_nav_snapshot(list_qs_raw, sol)
        sol.status = 'NO_BID'
        _release_review_claim(sol)
        sol.save(update_fields=[
            'status',
            'review_claimed_by', 'review_claimed_at', 'review_claim_expires_at',
        ])
        return _redirect_after_workbench_action(
            request,
            sol,
            list_qs_raw,
            queue_kind,
            list_nav_snapshot=list_nav_snapshot,
        )

    if action == 'next':
        _release_review_claim(sol)
        sol.save(update_fields=[
            'review_claimed_by', 'review_claimed_at', 'review_claim_expires_at',
        ])
        return _redirect_after_workbench_action(request, sol, list_qs_raw, queue_kind)

    messages.warning(request, 'Unknown action.')
    q = urllib.parse.urlencode({'list_qs': list_qs_raw}) if list_qs_raw else ''
    url = reverse('sales:solicitation_detail', args=[sol.solicitation_number])
    return redirect(f'{url}?{q}' if q else url)


@login_required
def solicitation_list(request):
    """
    Lists solicitations with filtering and pagination.
    Default: all pipeline statuses (LIST_PIPELINE_STATUSES); optional ?tab= / toggles / chips.
    Annotates each solicitation with first_line; list rows use live_match_count
    (dibbs_solicitation_match_counts view via Subquery in _list_qs_before_tab).
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        sol_ids = request.POST.getlist('sol_ids')
        if action == 'reassign_bucket' and sol_ids:
            new_bucket = request.POST.get('new_bucket', '').strip()
            bucket_note = request.POST.get('bucket_note', '').strip()
            valid_buckets = [b[0] for b in Solicitation.BUCKET_CHOICES]
            if new_bucket in valid_buckets:
                update_kwargs = {
                    'bucket': new_bucket,
                    'bucket_assigned_by': 'manual',
                    'hubzone_requested_by': bucket_note,
                }
                Solicitation.objects.filter(id__in=sol_ids).update(**update_kwargs)
                label = dict(Solicitation.BUCKET_CHOICES).get(new_bucket, new_bucket)
                messages.success(request, f"{len(sol_ids)} solicitation(s) moved to {label}.")
        return redirect(request.get_full_path())

    import datetime

    q = request.GET.get('q', '').strip()
    set_aside = request.GET.get('set_aside', '')
    status = request.GET.get('status', '')
    item_type = request.GET.get('item_type', '')
    has_matches_on = (request.GET.get('has_matches') or '').strip() == '1'
    has_approved_on = (request.GET.get('has_approved_source') or '').strip() == '1'

    active_tab = _list_tab_from_params(request.GET)

    qs = _build_list_queryset(request.GET)
    total_count = qs.count()
    first_sol_number = qs.values_list('solicitation_number', flat=True).first()
    eligible_for_mass_pass_count = qs.filter(status__in=['New', 'Active']).count()

    distinct_set_aside_codes = list(
        Solicitation.objects.exclude(status='Archived')
        .exclude(small_business_set_aside__isnull=True)
        .exclude(small_business_set_aside='')
        .values_list('small_business_set_aside', flat=True)
        .distinct()
        .order_by('small_business_set_aside')
    )
    set_aside_dropdown = [('', 'All Set-Asides')]
    for code in distinct_set_aside_codes:
        label = SET_ASIDE_LABELS.get(code, code)
        set_aside_dropdown.append((code, label))
    if set_aside and set_aside not in distinct_set_aside_codes:
        set_aside_dropdown.append((set_aside, SET_ASIDE_LABELS.get(set_aside, set_aside)))

    status_label_map = dict(Solicitation.STATUS_CHOICES)
    pipeline_status_choices = [
        (s, status_label_map[s]) for s in LIST_PIPELINE_STATUSES if s in status_label_map
    ]

    saved_for_list = list(
        SavedFilter.objects.filter(
            Q(is_system=True) | Q(user=request.user, is_system=False),
        ).order_by('is_system', 'name')
    )
    system_chips = [sf for sf in saved_for_list if sf.is_system]
    user_chips = [sf for sf in saved_for_list if not sf.is_system]
    active_canon = _canonical_list_filter_params_from_get(request.GET)
    active_chip_id = _find_matching_saved_filter_pk(saved_for_list, active_canon)
    show_save_filter = active_chip_id is None and bool(active_canon)
    filter_params_for_save_json = json.dumps(active_canon)
    user_chips_json = json.dumps([
        {'id': c.pk, 'name': c.name, 'filter_params': c.filter_params}
        for c in user_chips
    ])
    system_chip_rows = [
        {
            'pk': c.pk,
            'name': c.name,
            'url': _saved_filter_list_url(c.filter_params),
            'is_active': c.pk == active_chip_id,
        }
        for c in system_chips
    ]
    user_chip_rows = [
        {
            'pk': c.pk,
            'name': c.name,
            'url': _saved_filter_list_url(c.filter_params),
            'is_active': c.pk == active_chip_id,
        }
        for c in user_chips
    ]

    User = get_user_model()
    share_users = list(
        User.objects.filter(is_active=True)
        .exclude(pk=request.user.pk)
        .values('pk', 'first_name', 'last_name', 'username')
        .order_by('first_name', 'last_name')
    )
    share_users_json = json.dumps(share_users)

    # Toggle URLs for has_matches / has_approved_source (preserve other filters, omit page/active_chip).
    base_get = {
        k: v for k, v in request.GET.items()
        if k not in _LIST_FILTER_UI_KEYS
    }

    def _qs_url(extra=None, omit=None):
        d = dict(base_get)
        omit = omit or ()
        for k in omit:
            d.pop(k, None)
        if extra:
            d.update(extra)
        return f"{reverse('sales:solicitation_list')}?{urllib.parse.urlencode(d)}"

    toggle_has_matches_href = _qs_url(omit=('has_matches',)) if has_matches_on else _qs_url({'has_matches': '1'})
    toggle_has_approved_href = (
        _qs_url(omit=('has_approved_source',)) if has_approved_on else _qs_url({'has_approved_source': '1'})
    )

    # Column sort state for header links (must match _apply_list_sort)
    sort_param = (request.GET.get('sort') or '').strip()
    if sort_param.startswith('-'):
        sort_field = sort_param[1:]
    else:
        sort_field = sort_param
    if sort_field not in SORTABLE_FIELDS:
        sort_param = ''

    today = datetime.date.today()

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Attach first_line and overdue flag to each solicitation in the page
    for sol in page_obj:
        sol_lines = list(sol.lines.all())
        sol.first_line = sol_lines[0] if sol_lines else None
        sol.set_aside_display = SET_ASIDE_LABELS.get(sol.small_business_set_aside or '', '')
        sol.is_overdue = bool(sol.return_by_date and sol.return_by_date < today)

    filter_params = {
        k: v for k, v in request.GET.items()
        if k not in _LIST_FILTER_UI_KEYS
    }
    filter_snapshot = urllib.parse.urlencode(filter_params)
    filter_params_no_tab = {
        k: v for k, v in request.GET.items()
        if k not in _LIST_FILTER_UI_KEYS and k != 'tab'
    }
    filter_params_no_sort = {
        k: v for k, v in request.GET.items()
        if k not in _LIST_FILTER_UI_KEYS and k != 'sort'
    }

    # Next sort value per column for 3-state toggle: default -> asc -> desc -> default
    def next_sort(current, asc_val):
        if current == asc_val:
            return f"-{asc_val}"
        if current == f"-{asc_val}":
            return ""
        return asc_val

    sort_param_val = sort_param or ""
    sort_links = {
        "solicitation_number": next_sort(sort_param_val, "solicitation_number"),
        "nsn": next_sort(sort_param_val, "nsn"),
        "nomenclature": next_sort(sort_param_val, "nomenclature"),
        "quantity": next_sort(sort_param_val, "quantity"),
        "set_aside": next_sort(sort_param_val, "set_aside"),
        "return_by_date": next_sort(sort_param_val, "return_by_date"),
        "status": next_sort(sort_param_val, "status"),
        "match_count": next_sort(sort_param_val, "match_count"),
    }

    return render(request, "sales/solicitations/list.html", {
        "page_obj": page_obj,
        "set_aside_choices": SET_ASIDE_CHOICES,
        "set_aside_dropdown": set_aside_dropdown,
        "status_choices": Solicitation.STATUS_CHOICES,
        "pipeline_status_choices": pipeline_status_choices,
        "current_filters": {
            "q": q,
            "set_aside": set_aside,
            "status": status,
            "item_type": item_type,
            "has_matches": has_matches_on,
            "has_approved_source": has_approved_on,
        },
        "active_tab": active_tab,
        "system_chips": system_chips,
        "user_chips": user_chips,
        "system_chip_rows": system_chip_rows,
        "user_chip_rows": user_chip_rows,
        "active_chip_id": active_chip_id,
        "show_save_filter": show_save_filter,
        "filter_params_for_save_json": filter_params_for_save_json,
        "user_chips_json": user_chips_json,
        "share_users": share_users,
        "share_users_json": share_users_json,
        "toggle_has_matches_href": toggle_has_matches_href,
        "toggle_has_approved_href": toggle_has_approved_href,
        "sort_param": sort_param_val,
        "sort_links": sort_links,
        "filter_querystring": urllib.parse.urlencode(filter_params),
        "filter_snapshot": filter_snapshot,
        "filter_querystring_no_tab": urllib.parse.urlencode(filter_params_no_tab),
        "filter_querystring_no_sort": urllib.parse.urlencode(filter_params_no_sort),
        "eligible_for_mass_pass_count": eligible_for_mass_pass_count,
        "total_count": total_count,
        "first_sol_number": first_sol_number,
    })


def _workbench_approved_sources_display(line):
    """
    Approved source rows for the workbench NSN: internal Supplier name first,
    then SAMEntityCache.entity_name (reads only; chunked cage_code__in).
    """
    if not line:
        return []
    normalized_nsn = (line.nsn or "").replace("-", "").strip()
    if not normalized_nsn:
        return []
    rows = list(
        ApprovedSource.objects.filter(nsn=normalized_nsn).only(
            "approved_cage", "part_number"
        )
    )
    if not rows:
        return []
    unique_cages = []
    seen_cage = set()
    for r in rows:
        c = normalize_cage_code(r.approved_cage)
        if not c or c in seen_cage:
            continue
        seen_cage.add(c)
        unique_cages.append(c)
    supplier_by_norm = {}
    for chunk in _mass_pass_chunked(unique_cages, 100):
        for s in Supplier.objects.filter(cage_code__in=chunk, archived=False):
            supplier_by_norm[normalize_cage_code(s.cage_code)] = s
    sam_name_map = {}
    for chunk in _mass_pass_chunked(unique_cages, 100):
        for ent in SAMEntityCache.objects.filter(cage_code__in=chunk).only(
            "cage_code", "entity_name"
        ):
            sam_name_map[normalize_cage_code(ent.cage_code)] = ent.entity_name
    out = []
    for r in rows:
        cage_norm = normalize_cage_code(r.approved_cage)
        sup = supplier_by_norm.get(cage_norm) if cage_norm else None
        if sup:
            name = sup.name
            supplier_id = sup.id
            has_supplier = True
        else:
            supplier_id = None
            has_supplier = False
            raw_sam = sam_name_map.get(cage_norm) if cage_norm else None
            name = raw_sam.strip() if (raw_sam and raw_sam.strip()) else None
        out.append(
            {
                "cage": r.approved_cage,
                "part_number": r.part_number,
                "name": name,
                "supplier_id": supplier_id,
                "has_supplier": has_supplier,
            }
        )
    return out


def _workbench_procurement_packaging_context(solicitation, line):
    sol_nsn = _normalize_nsn(line.nsn) if line else ""
    procurement_history = (
        NsnProcurementHistory.objects.filter(nsn=sol_nsn).order_by("-award_date")
        if sol_nsn
        else NsnProcurementHistory.objects.none()
    )
    packaging = SolPackaging.objects.filter(
        solicitation_number=solicitation.solicitation_number,
    ).first()
    return {
        "procurement_history": procurement_history,
        "packaging": packaging,
        "sol_number": solicitation.solicitation_number,
        "has_pdf_blob": bool(solicitation.pdf_blob),
    }


@login_required
def solicitation_history_packaging_partial(request, sol_number):
    solicitation = get_object_or_404(
        Solicitation.objects.prefetch_related("lines"),
        solicitation_number=sol_number,
    )
    line = solicitation.lines.order_by("line_number", "id").first()
    ctx = _workbench_procurement_packaging_context(solicitation, line)
    return render(
        request,
        "sales/solicitations/partials/workbench_procurement_packaging.html",
        ctx,
    )


@login_required
@require_POST
def solicitation_reparse(request, sol_number):
    """
    Re-run PDF text extraction for procurement history (Section A/B) and
    packaging (Section D) using the stored pdf_blob.
    """
    from sales.services.dibbs_pdf import (
        parse_packaging_data,
        parse_procurement_history,
        save_procurement_history,
        save_sol_packaging,
    )

    sol = get_object_or_404(Solicitation, solicitation_number=sol_number)
    blob = sol.pdf_blob
    if not blob:
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "No PDF on file. Use “View RFQ PDF” to fetch the file first, "
                    "then try Re-parse."
                ),
            },
            status=400,
        )

    body = bytes(blob)
    key = sol.solicitation_number.strip().upper()
    rows = parse_procurement_history(body, key)
    hist_saved = save_procurement_history(rows)
    pack = parse_packaging_data(body, key)
    pack_saved = save_sol_packaging(key, pack)

    now = timezone.now()
    sol.pdf_data_pulled = now
    sol.save(update_fields=["pdf_data_pulled"])

    return JsonResponse(
        {
            "ok": True,
            "message": "Procurement history and packaging were refreshed from the stored PDF.",
            "history_rows_parsed": len(rows),
            "history_rows_saved": hist_saved,
            "packaging_saved": pack_saved,
        }
    )


@login_required
def solicitation_pdf_view(request, sol_number):
    from sales.services.dibbs_pdf import fetch_pdf_for_sol

    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)

    if solicitation.pdf_blob:
        payload = bytes(solicitation.pdf_blob)
        resp = HttpResponse(payload, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{sol_number}.pdf"'
        resp["X-SBZ-PDF-From-Cache"] = "1"
        return resp

    solicitation.pdf_fetch_status = "FETCHING"
    solicitation.save(update_fields=["pdf_fetch_status"])

    body = fetch_pdf_for_sol(sol_number)
    now = timezone.now()

    if body:
        solicitation.pdf_blob = body
        solicitation.pdf_fetched_at = now
        solicitation.pdf_fetch_status = "DONE"
        solicitation.pdf_data_pulled = now
        solicitation.save(
            update_fields=[
                "pdf_blob",
                "pdf_fetched_at",
                "pdf_fetch_status",
                "pdf_data_pulled",
            ]
        )
        resp = HttpResponse(body, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{sol_number}.pdf"'
        resp["X-SBZ-PDF-Fresh"] = "1"
        return resp

    Solicitation.objects.filter(pk=solicitation.pk).update(
        pdf_fetch_status="FAILED",
        pdf_fetch_attempts=F("pdf_fetch_attempts") + 1,
    )
    return HttpResponse(
        "Could not fetch the solicitation PDF from DIBBS. "
        "Check Playwright/Chromium or try again later.",
        status=502,
        content_type="text/plain; charset=utf-8",
    )


@login_required
def solicitation_workbench(request, sol_number):
    """
    Unified solicitation Review Workbench: triage data, supplier queue actions,
    research/pass, and list_qs/session-aware prev–next navigation.
    """
    solicitation = get_object_or_404(
        Solicitation.objects.select_related("import_batch").prefetch_related("lines"),
        solicitation_number=sol_number,
    )
    list_qs_raw = ""
    if request.method == "POST":
        list_qs_raw = (request.POST.get("list_qs") or "").strip()
    if not list_qs_raw:
        list_qs_raw = (request.GET.get("list_qs") or "").strip()

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action in ("research", "pass", "next"):
            return _workbench_post_action(
                request, solicitation, action, list_qs_raw
            )
        messages.warning(request, "Unsupported form submission.")
        return redirect("sales:solicitation_detail", sol_number=sol_number)

    now = timezone.now()
    workbench_claim_blocked = False
    if solicitation.status in ("New", "Active"):
        kind = _infer_queue_kind(solicitation)
        queue_key, index_key = _queue_session_keys(kind)
        queue = list(request.session.get(queue_key) or [])
        if _is_claimed_by_other(solicitation, request.user, now):
            if solicitation.pk in queue:
                cur_idx = queue.index(solicitation.pk)
                next_pk = None
                for idx in range(cur_idx + 1, len(queue)):
                    pk = queue[idx]
                    cand = Solicitation.objects.filter(pk=pk).first()
                    if not cand:
                        continue
                    if cand.status not in _valid_statuses_for_queue(kind):
                        continue
                    if _is_claimed_by_other(cand, request.user, now):
                        continue
                    next_pk = pk
                    request.session[index_key] = idx
                    request.session.modified = True
                    break
                if next_pk:
                    nxt = Solicitation.objects.get(pk=next_pk)
                    return redirect(
                        "sales:solicitation_detail",
                        sol_number=nxt.solicitation_number,
                    )
                messages.warning(
                    request,
                    "Queue complete — all remaining sols are claimed by other reps.",
                )
                return redirect(_queue_list_redirect(kind))
            workbench_claim_blocked = True
        else:
            solicitation.review_claimed_by = request.user
            solicitation.review_claimed_at = now
            solicitation.review_claim_expires_at = now + timedelta(minutes=20)
            solicitation.save(update_fields=[
                "review_claimed_by",
                "review_claimed_at",
                "review_claim_expires_at",
            ])

    prev_sol, next_sol, nav_record_num, nav_total = _workbench_record_counter(
        solicitation, list_qs_raw, request
    )

    queued_rfq_count = SupplierRFQ.objects.filter(
        line__solicitation=solicitation,
        status="QUEUED",
    ).count()

    line = solicitation.lines.order_by("line_number", "id").first()
    pipeline_steps = _build_pipeline_steps(solicitation.status)
    match_count = (
        SupplierMatch.objects.filter(line__solicitation=solicitation)
        .exclude(match_method="MANUAL")
        .count()
    )
    rfq_count = SupplierRFQ.objects.filter(
        line__solicitation=solicitation,
    ).count()
    quote_count = SupplierQuote.objects.filter(
        line__solicitation=solicitation,
    ).count()

    contact_log = (
        SupplierContactLog.objects.filter(solicitation=solicitation)
        .select_related("logged_by", "supplier")
        .order_by("-logged_at")[:50]
    )

    solicitation.set_aside_display = SET_ASIDE_LABELS.get(
        solicitation.small_business_set_aside or "", ""
    )

    queued_supplier_ids = set(
        SupplierRFQ.objects.filter(
            line__solicitation=solicitation,
            status="QUEUED",
        ).values_list("supplier_id", flat=True)
    )

    _rpc = _workbench_procurement_packaging_context(solicitation, line)
    procurement_history = _rpc["procurement_history"]
    packaging = _rpc["packaging"]
    has_pdf_blob = _rpc["has_pdf_blob"]
    approved_sources_display = _workbench_approved_sources_display(line)
    sidebar_ctx = _workbench_sidebar_context(solicitation)
    tier1_matches = sidebar_ctx["tier1_matches"]
    tier2_matches = sidebar_ctx["tier2_matches"]
    tier3_matches = sidebar_ctx["tier3_matches"]
    queued_cages = sidebar_ctx["queued_cages"]
    no_quote_cages = sidebar_ctx["no_quote_cages"]
    sam_cache_map = sidebar_ctx["sam_cache_map"]
    rfqs_queued = SupplierRFQ.objects.filter(
        line__solicitation=solicitation,
        status="QUEUED",
    ).exists()

    nsn_raw = getattr(line, "nsn", None) if line else None
    last_award = None
    last_award_we_won = False
    if nsn_raw:
        last_award = (
            DibbsAward.objects.filter(nsn__iexact=nsn_raw)
            .exclude(total_contract_price=None)
            .order_by("-award_date", "-id")
            .first()
        )
        if last_award:
            last_award_we_won = WeWonAward.objects.filter(pk=last_award.pk).exists()

    today = timezone.now().date()
    return_by_urgent = bool(
        solicitation.return_by_date
        and (solicitation.return_by_date - today).days <= 3
    )
    show_triage_actions = solicitation.status in (
        "New", "Active", "Matching", "RESEARCH",
    )
    show_research_button = solicitation.status in ("New", "Active", "Matching")

    return render(
        request,
        "sales/solicitations/detail.html",
        {
            "solicitation": solicitation,
            "line": line,
            "pipeline_steps": pipeline_steps,
            "match_count": match_count,
            "rfq_count": rfq_count,
            "quote_count": quote_count,
            "contact_log": contact_log,
            "queued_supplier_ids": queued_supplier_ids,
            "prev_sol": prev_sol,
            "next_sol": next_sol,
            "list_qs": list_qs_raw,
            "queued_rfq_count": queued_rfq_count,
            "no_quote_cages": no_quote_cages,
            "last_award": last_award,
            "last_award_we_won": last_award_we_won,
            "procurement_history": procurement_history,
            "packaging": packaging,
            "has_pdf_blob": has_pdf_blob,
            "approved_sources_display": approved_sources_display,
            "tier1_matches": tier1_matches,
            "tier2_matches": tier2_matches,
            "tier3_matches": tier3_matches,
            "rfqs_queued": rfqs_queued,
            "queued_cages": queued_cages,
            "sam_cache_map": sam_cache_map,
            "return_by_urgent": return_by_urgent,
            "nav_record_num": nav_record_num,
            "nav_total": nav_total,
            "workbench_claim_blocked": workbench_claim_blocked,
            "show_triage_actions": show_triage_actions,
            "show_research_button": show_research_button,
        },
    )


@login_required
def solicitation_workbench_sidebar_partial(request, sol_number):
    """HTMX/full GET: matches table + manual supplier card (same context as workbench right rail)."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    return render(
        request,
        "sales/solicitations/partials/workbench_sidebar_matches.html",
        _workbench_sidebar_context(solicitation),
    )


@login_required
@require_POST
def no_bid(request, sol_number):
    """Mark a solicitation as No-Bid and redirect back to detail page."""
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    solicitation.status = "NO_BID"
    solicitation.save(update_fields=["status"])
    messages.success(request, f"{sol_number} marked No-Bid.")
    return redirect("sales:solicitation_detail", sol_number=sol_number)


@login_required
def global_search(request):
    """
    Searches solicitation_number and nomenclature across all SolicitationLine records.
    Returns JSON for topbar typeahead OR full page results.
    GET ?q=<term>&fmt=json  → JSON list of up to 8 results for typeahead
    GET ?q=<term>           → full search results page
    """
    q = request.GET.get("q", "").strip()
    fmt = request.GET.get("fmt", "")

    if q:
        sol_qs = (
            Solicitation.objects.filter(
                Q(solicitation_number__icontains=q)
                | Q(lines__nomenclature__icontains=q)
                | Q(lines__nsn__icontains=q)
            )
            .distinct()
            .select_related("import_batch")
            .prefetch_related("lines")
            .order_by("-import_date")[:50]
        )
    else:
        sol_qs = Solicitation.objects.none()

    if fmt == "json":
        results = []
        for sol in sol_qs[:8]:
            line = sol.lines.first()
            results.append({
                "sol_number": sol.solicitation_number,
                "nsn": line.nsn if line else "",
                "nomenclature": line.nomenclature if line else "",
                "status": sol.status,
                "url": reverse("sales:solicitation_detail", args=[sol.solicitation_number]),
            })
        return JsonResponse({"results": results})

    for sol in sol_qs:
        sol.first_line = sol.lines.order_by("line_number", "id").first()
    return render(
        request,
        "sales/search_results.html",
        {"query": q, "solicitations": sol_qs},
    )


CLOSED_STATUSES = ["NO_BID", "Archived", "BID_SUBMITTED", "WON", "LOST"]
STATUS_MAP = {
    "no_bid": "NO_BID",
    "archived": "Archived",
    "bid_submitted": "BID_SUBMITTED",
    "won": "WON",
    "lost": "LOST",
}


@login_required
def closed_list(request):
    """
    Read-only view for terminal solicitations (closed pipeline outcomes).
    Paginated at 50 per page, default order return_by_date descending.
    Optional ?status= filter: no_bid, archived, bid_submitted, won, lost, or all / omitted.
    """
    qs = (
        Solicitation.objects.filter(status__in=CLOSED_STATUSES)
        .select_related("import_batch")
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=SolicitationLine.objects.order_by("line_number", "id"),
            )
        )
        .order_by("-return_by_date", "-solicitation_number")
    )

    raw_status = (request.GET.get("status") or "").strip().lower()
    if raw_status == "all":
        raw_status = ""
    active_status_filter = ""
    if raw_status and raw_status in STATUS_MAP:
        qs = qs.filter(status=STATUS_MAP[raw_status])
        active_status_filter = raw_status

    set_aside = request.GET.get("set_aside", "").strip()
    item_type = request.GET.get("item_type", "").strip()
    q = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if set_aside:
        qs = qs.filter(small_business_set_aside=set_aside)
    if item_type:
        qs = qs.filter(lines__item_type_indicator=item_type).distinct()
    if q:
        qs = qs.filter(
            Q(solicitation_number__icontains=q)
            | Q(lines__nomenclature__icontains=q)
            | Q(lines__nsn__icontains=q)
        ).distinct()
    if date_from:
        try:
            qs = qs.filter(return_by_date__gte=date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            qs = qs.filter(return_by_date__lte=date.fromisoformat(date_to))
        except ValueError:
            pass

    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    for sol in page_obj:
        sol_lines = list(sol.lines.all())
        sol.first_line = sol_lines[0] if sol_lines else None
        sol.set_aside_display = SET_ASIDE_LABELS.get(sol.small_business_set_aside or "", "")

    filter_params = {k: v for k, v in request.GET.items() if k != "page"}
    filter_querystring = urllib.parse.urlencode(filter_params)
    filter_qs_base = urllib.parse.urlencode(
        [(k, v) for k, v in request.GET.items() if k not in ("page", "status")]
    )

    total_closed_terminal = Solicitation.objects.filter(
        status__in=CLOSED_STATUSES
    ).count()

    return render(
        request,
        "sales/solicitations/closed.html",
        {
            "page_obj": page_obj,
            "total_closed_terminal": total_closed_terminal,
            "filter_querystring": filter_querystring,
            "filter_qs_base": filter_qs_base,
            "set_aside_choices": SET_ASIDE_CHOICES,
            "active_status_filter": active_status_filter,
            "current_filters": {
                "set_aside": set_aside,
                "item_type": item_type,
                "q": q,
                "date_from": date_from,
                "date_to": date_to,
            },
        },
    )


def _queue_filter_params_present(data):
    if not data:
        return False
    return any((data.get(k) or '').strip() for k in (
        'set_aside', 'return_date_from', 'return_date_to', 'search', 'match_exists',
    ))


def _review_queue_page_context(request, statuses, data):
    data = dict(data or {})
    use_filters = _queue_filter_params_present(data)
    filtered_qs = _review_queue_base_queryset(
        request.user, statuses, data if use_filters else None
    )
    total_pool = _review_queue_base_queryset(request.user, statuses, None).count()
    matching_count = filtered_qs.count() if use_filters else total_pool
    return {
        'set_aside_choices': SET_ASIDE_CHOICES,
        'form_set_aside': (data.get('set_aside') or '').strip(),
        'form_return_date_from': (data.get('return_date_from') or '').strip(),
        'form_return_date_to': (data.get('return_date_to') or '').strip(),
        'form_search': (data.get('search') or '').strip(),
        'form_match_exists': (data.get('match_exists') or '').strip(),
        'matching_count': matching_count,
        'total_pool_count': total_pool,
    }


@login_required
@require_POST
def sol_mass_pass(request):
    """
    Mass Pass / No Bid from the solicitation list.

    - ``mass_pass_all=1`` + ``filter_qs``: rebuild the list queryset from the same
      GET params as the current filtered view; one ``QuerySet.update`` for all rows
      with status New or Active only (excludes RFQ_SENT, QUOTING, etc.). Rows with
      QUEUED RFQs are skipped (same guard as single-record Pass on the workbench).
    - ``sol_ids``: legacy page-scoped pass for checked rows (still restricted to
      New/Active at the database).
    """
    safe_statuses = ['New', 'Active']
    filter_qs = (request.POST.get('filter_qs') or '').strip()
    if request.POST.get('mass_pass_all') == '1' and filter_qs:
        try:
            list_params = dict(
                urllib.parse.parse_qsl(filter_qs, keep_blank_values=True)
            )
        except (ValueError, TypeError):
            messages.error(request, 'Invalid filter parameters.')
            return redirect('sales:solicitation_list')

        base = _build_list_queryset(list_params)
        queued_subq = SupplierRFQ.objects.filter(
            line__solicitation_id=OuterRef('pk'),
            status='QUEUED',
        )
        qs = (
            base.filter(status__in=safe_statuses)
            .annotate(_has_queued_rfq=Exists(queued_subq))
            .filter(_has_queued_rfq=False)
        )
        snapshot = list(qs.values('id', 'status'))
        snapshot_data = [
            {'sol_id': row['id'], 'prior_status': row['status']} for row in snapshot
        ]
        sol_count = len(snapshot_data)
        filter_desc = filter_qs or 'page selection'
        if sol_count > 0:
            MassPassLog.objects.create(
                performed_by=request.user,
                filter_description=filter_desc,
                sol_count=sol_count,
                snapshot=snapshot_data,
            )
        updated = qs.update(status='NO_BID')
        messages.success(
            request,
            f'{updated} solicitation(s) marked No Bid (all New/Active in this view '
            'without queued RFQs).',
        )
        return redirect(f"{reverse('sales:solicitation_list')}?{filter_qs}")

    sol_ids = request.POST.getlist('sol_ids')
    if not sol_ids:
        messages.warning(request, 'No solicitations selected.')
        return redirect('sales:solicitation_list')

    qs_page = Solicitation.objects.filter(
        pk__in=sol_ids,
        status__in=safe_statuses,
    )
    snapshot = list(qs_page.values('id', 'status'))
    snapshot_data = [
        {'sol_id': row['id'], 'prior_status': row['status']} for row in snapshot
    ]
    sol_count = len(snapshot_data)
    filter_desc = (request.POST.get('filter_qs') or '').strip() or 'page selection'
    if sol_count > 0:
        MassPassLog.objects.create(
            performed_by=request.user,
            filter_description=filter_desc,
            sol_count=sol_count,
            snapshot=snapshot_data,
        )
    updated = qs_page.update(status='NO_BID')

    messages.success(request, f'{updated} solicitation(s) marked No Bid.')
    return redirect('sales:solicitation_list')


@login_required
def mass_pass_history(request):
    logs = MassPassLog.objects.select_related('performed_by', 'undone_by').order_by(
        '-performed_at'
    )
    return render(
        request,
        'sales/solicitations/mass_pass_history.html',
        {'logs': logs},
    )


@login_required
@require_POST
def mass_pass_undo(request, log_pk):
    log = get_object_or_404(MassPassLog, pk=log_pk)

    if log.is_undone:
        messages.error(request, 'This mass pass has already been undone.')
        return redirect('sales:mass_pass_history')

    sol_ids_in_snapshot = [row['sol_id'] for row in log.snapshot]

    restored_count = 0
    for chunk in _mass_pass_chunked(sol_ids_in_snapshot):
        restored_count += Solicitation.objects.filter(
            id__in=chunk,
            status='NO_BID',
        ).update(status='Active')

    log.undone_by = request.user
    log.undone_at = timezone.now()
    log.save(update_fields=['undone_by', 'undone_at'])

    skipped = log.sol_count - restored_count
    messages.success(
        request,
        f'Undo complete. {restored_count} solicitation(s) restored to Active. '
        f'{skipped} skipped (already moved forward).',
    )
    return redirect('sales:mass_pass_history')


@login_required
@require_POST
def sol_unbid(request, sol_number):
    sol = get_object_or_404(Solicitation, solicitation_number=sol_number)

    if sol.status != 'NO_BID':
        messages.error(request, 'This solicitation is not currently No-Bid.')
        return redirect('sales:solicitation_detail', sol_number=sol_number)

    sol.status = 'Active'
    sol.save(update_fields=['status'])

    messages.success(request, f'{sol_number} restored to Active.')
    return redirect('sales:solicitation_detail', sol_number=sol_number)


@login_required
def sol_review_queue(request):
    """
    Sol Review Queue entry point.
    GET: render filter screen.
    POST: build filtered queue, write queue to session, redirect to first sol.
    """
    statuses = ['New', 'Active']
    if request.method == 'POST':
        qs = _review_queue_base_queryset(request.user, statuses, request.POST)
        queue_pks = list(qs.values_list('pk', flat=True))
        request.session['sol_review_queue'] = queue_pks
        request.session['sol_review_index'] = 0
        if not queue_pks:
            messages.warning(request, 'No solicitations match your filters.')
            ctx = _review_queue_page_context(request, statuses, request.POST)
            ctx['page_title'] = 'Sol Review Queue'
            return render(request, 'sales/solicitations/review_queue.html', ctx)
        first_sol = Solicitation.objects.filter(pk=queue_pks[0]).first()
        if first_sol:
            return redirect(
                'sales:solicitation_detail',
                sol_number=first_sol.solicitation_number,
            )
        return redirect('sales:sol_review_queue')
    ctx = _review_queue_page_context(request, statuses, request.GET)
    ctx['page_title'] = 'Sol Review Queue'
    return render(request, 'sales/solicitations/review_queue.html', ctx)


@login_required
def research_queue(request):
    """
    Research Queue entry — same filters as Sol Review but status RESEARCH only.
    """
    statuses = ['RESEARCH']
    if request.method == 'POST':
        qs = _review_queue_base_queryset(request.user, statuses, request.POST)
        queue_pks = list(qs.values_list('pk', flat=True))
        request.session['research_queue'] = queue_pks
        request.session['research_index'] = 0
        if not queue_pks:
            messages.warning(request, 'No solicitations match your filters.')
            ctx = _review_queue_page_context(request, statuses, request.POST)
            ctx['page_title'] = 'Research Queue'
            return render(request, 'sales/solicitations/research_queue.html', ctx)
        first_sol = Solicitation.objects.filter(pk=queue_pks[0]).first()
        if first_sol:
            return redirect(
                'sales:solicitation_detail',
                sol_number=first_sol.solicitation_number,
            )
        return redirect('sales:research_queue')
    ctx = _review_queue_page_context(request, statuses, request.GET)
    ctx['page_title'] = 'Research Queue'
    return render(request, 'sales/solicitations/research_queue.html', ctx)


@login_required
def sol_review_legacy_redirect(request, sol_pk):
    """Old `/solicitations/review/<pk>/` bookmarks redirect to the workbench."""
    sol = get_object_or_404(Solicitation, pk=sol_pk)
    return redirect(
        'sales:solicitation_detail',
        sol_number=sol.solicitation_number,
    )


@login_required
def supplier_search_ajax(request):
    """
    AJAX endpoint for manual supplier search on the solicitation workbench.
    Returns JSON list of matching suppliers from contracts_supplier table.
    """
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    suppliers = (
        Supplier.objects.filter(archived=False)
        .filter(Q(name__icontains=q) | Q(cage_code__icontains=q))
        .annotate(last_quote_date=Max('dibbs_quotes__quote_date'))
        .values('id', 'name', 'cage_code', 'email', 'last_quote_date')[:20]
    )
    results = []
    for row in suppliers:
        r = dict(row)
        lqd = r.get('last_quote_date')
        if lqd is not None:
            r['last_quote_date'] = lqd.isoformat()
        results.append(r)
    return JsonResponse({'results': results})


@login_required
@require_POST
def sol_remove_research(request, sol_pk):
    """
    Remove Research flag from a sol — returns it to Active (active triage pool).
    """
    sol = get_object_or_404(Solicitation, pk=sol_pk, status='RESEARCH')
    sol.status = 'Active'
    sol.research_flagged_by = None
    sol.research_flagged_at = None
    sol.save(update_fields=['status', 'research_flagged_by', 'research_flagged_at'])
    messages.success(
        request,
        f'Research flag removed from {sol.solicitation_number}.',
    )
    next_qs = (request.POST.get('next_list_qs') or '').strip()
    if (
        next_qs
        and len(next_qs) <= 4096
        and not any(
            bad in next_qs.lower()
            for bad in ('http://', 'https://', '//', '<', '\n', '\r')
        )
    ):
        return redirect(f"{reverse('sales:solicitation_list')}?{next_qs}")
    return redirect(f"{reverse('sales:solicitation_list')}?tab=research")


def _parse_saved_filter_params_payload(raw):
    try:
        parsed = json.loads(raw or '')
    except json.JSONDecodeError:
        return None, 'Invalid filter_params JSON'
    if not isinstance(parsed, dict):
        return None, 'filter_params must be a JSON object'
    normalized = {}
    for k, v in parsed.items():
        sk = str(k).strip()
        if not sk or sk in _LIST_FILTER_UI_KEYS:
            continue
        normalized[sk] = (str(v) if v is not None else '').strip()
    normalized = {k: v for k, v in normalized.items() if v != ''}
    return normalized, None


@login_required
@require_POST
def saved_filter_create(request):
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'Name is required'}, status=400)
    if len(name) > 100:
        return JsonResponse({'error': 'Name is too long'}, status=400)
    parsed, err = _parse_saved_filter_params_payload(
        request.POST.get('filter_params') or ''
    )
    if err:
        return JsonResponse({'error': err}, status=400)
    obj = SavedFilter.objects.create(
        user=request.user,
        name=name,
        filter_params=parsed,
        is_system=False,
    )
    return JsonResponse({'id': obj.pk, 'name': obj.name})


@login_required
@require_POST
def saved_filter_update(request):
    try:
        pk = int((request.POST.get('filter_id') or '').strip())
    except ValueError:
        return JsonResponse({'error': 'Invalid filter id'}, status=400)
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'Name is required'}, status=400)
    if len(name) > 100:
        return JsonResponse({'error': 'Name is too long'}, status=400)
    sf = SavedFilter.objects.filter(
        pk=pk, user=request.user, is_system=False,
    ).first()
    if not sf:
        return JsonResponse({'error': 'Forbidden'}, status=403)
    sf.name = name
    sf.save(update_fields=['name'])
    return JsonResponse({'id': sf.pk, 'name': sf.name})


@login_required
@require_POST
def saved_filter_delete(request):
    try:
        pk = int((request.POST.get('filter_id') or '').strip())
    except ValueError:
        return JsonResponse({'error': 'Invalid filter id'}, status=400)
    sf = SavedFilter.objects.filter(
        pk=pk, user=request.user, is_system=False,
    ).first()
    if not sf:
        return JsonResponse({'error': 'Forbidden'}, status=403)
    sf.delete()
    return JsonResponse({'deleted': True})


@login_required
def saved_filter_share(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        filter_id = int((request.POST.get('filter_id') or '').strip())
    except ValueError:
        return JsonResponse({'error': 'Invalid filter id'}, status=400)

    try:
        target_user_id = int((request.POST.get('target_user_id') or '').strip())
    except ValueError:
        return JsonResponse({'error': 'Invalid user id'}, status=400)

    User = get_user_model()

    try:
        saved_filter = SavedFilter.objects.get(
            pk=filter_id,
            user=request.user,
            is_system=False,
        )
    except SavedFilter.DoesNotExist:
        return JsonResponse({'error': 'Filter not found'}, status=404)

    try:
        target_user = User.objects.get(
            pk=target_user_id,
            is_active=True,
        )
    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    if target_user == request.user:
        return JsonResponse(
            {'error': 'Cannot share with yourself'},
            status=400,
        )

    name = saved_filter.name
    if SavedFilter.objects.filter(
        user=target_user, name=name, is_system=False
    ).exists():
        name = f'{name} (shared)'

    SavedFilter.objects.create(
        user=target_user,
        name=name,
        filter_params=saved_filter.filter_params,
        is_system=False,
    )

    return JsonResponse({
        'shared': True,
        'target_name': target_user.get_full_name() or target_user.username,
    })


# URL name `solicitation_detail` still resolves to this view; alias for explicit imports.
solicitation_detail = solicitation_workbench
