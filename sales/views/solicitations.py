"""
Solicitation list and detail views.
"""
import urllib.parse
from datetime import date, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Count, Exists, F, Prefetch, Q, OuterRef, Subquery, Max
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
)
from sales.services.matching import _normalize_nsn
from sales.services.no_quote import get_no_quote_cage_set, normalize_cage_code
from suppliers.models import Supplier

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
VALID_TABS = frozenset({'matches', 'set_asides', 'unrestricted', 'research', 'nobid'})

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


def build_consolidated_supplier_list(sol, no_quote_cages):
    """
    Merge SupplierMatch rows and ApprovedSource rows for this solicitation's lines,
    deduped by normalized CAGE. Sorted: non–no-quote first, then by tier, then name.
    """
    lines = list(sol.lines.all())
    nsn_set = {_normalize_nsn(l.nsn) for l in lines if l.nsn}
    by_cage = {}

    matches = (
        SupplierMatch.objects.filter(line__solicitation=sol)
        .select_related('supplier')
    )
    for m in matches:
        sup = m.supplier
        cage = normalize_cage_code(sup.cage_code)
        if not cage:
            continue
        if cage not in by_cage:
            by_cage[cage] = {
                'supplier': sup,
                'cage_code': cage,
                'company_name': (sup.name or '').strip(),
                'sources': ['NSN Match'],
                'match_tier': m.match_tier,
                'is_no_quote': cage in no_quote_cages,
            }
        else:
            e = by_cage[cage]
            if 'NSN Match' not in e['sources']:
                e['sources'].append('NSN Match')
            e['match_tier'] = min(
                e['match_tier'] if e['match_tier'] is not None else 99,
                m.match_tier,
            )

    for n in nsn_set:
        if not n:
            continue
        for asrc in ApprovedSource.objects.filter(nsn=n):
            cage = normalize_cage_code(asrc.approved_cage)
            if not cage:
                continue
            cname = (asrc.company_name or '').strip()
            if cage not in by_cage:
                sup = Supplier.objects.filter(cage_code__iexact=cage, archived=False).first()
                by_cage[cage] = {
                    'supplier': sup,
                    'cage_code': cage,
                    'company_name': cname or (sup.name if sup else '') or cage,
                    'sources': ['Approved Source'],
                    'match_tier': None,
                    'is_no_quote': cage in no_quote_cages,
                }
            else:
                e = by_cage[cage]
                if 'Approved Source' not in e['sources']:
                    e['sources'].append('Approved Source')
                if not e['company_name'] and cname:
                    e['company_name'] = cname
                if e['supplier'] is None:
                    e['supplier'] = Supplier.objects.filter(
                        cage_code__iexact=cage, archived=False
                    ).first()
                    if e['supplier'] and not e['company_name']:
                        e['company_name'] = (e['supplier'].name or '').strip()

    rows = list(by_cage.values())
    rows.sort(
        key=lambda e: (
            e['is_no_quote'],
            e['match_tier'] if e['match_tier'] is not None else 99,
            (e['company_name'] or '').lower(),
        )
    )
    return rows


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


def _list_qs_before_tab(params):
    """
    Apply bucket / set-aside / status / item-type / search filters and match_count annotation.
    Does not apply tab filter, NO_BID rules, or column sort.
    """
    q = (params.get('q') or '').strip()
    set_aside = params.get('set_aside', '') or ''
    status = params.get('status', '') or ''
    item_type = params.get('item_type', '') or ''
    bucket = params.get('bucket', '') or ''

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

    qs = qs.annotate(match_count=Count('lines__supplier_matches', distinct=True))
    return qs


def _apply_list_tab_filter(qs, tab):
    if tab == 'nobid':
        return qs.filter(status='NO_BID')
    if tab == 'research':
        return qs.filter(status='RESEARCH')
    qs = qs.exclude(status='NO_BID')
    if tab == 'matches':
        return qs.filter(match_count__gt=0)
    if tab == 'set_asides':
        return qs.exclude(UNRESTRICTED_TAB_Q)
    if tab == 'unrestricted':
        return qs.filter(UNRESTRICTED_TAB_Q)
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
    else:
        order_field = sort_field

    order_by = ('-' + order_field,) if sort_desc else (order_field,)
    return qs.order_by(*order_by)


def _build_list_queryset(params):
    """
    Reconstruct the filtered solicitation queryset from GET-like params.
    Used by solicitation_list and solicitation_workbench (prev/next nav).
    """
    raw_tab = params.get('tab', 'matches')
    tab = raw_tab if raw_tab in VALID_TABS else 'matches'
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


def _redirect_after_workbench_action(request, sol, list_qs_raw, queue_kind_before_mutate):
    """
    After research / pass / next: next item in list_qs order (skip current), else session queue.
    queue_kind_before_mutate: _infer_queue_kind(sol) before any status-changing save.
    """
    enc = list_qs_raw or ''
    if enc.strip():
        try:
            list_params = dict(
                urllib.parse.parse_qsl(enc, keep_blank_values=True)
            )
            nav_qs = _build_list_queryset(list_params)
            sol_numbers = list(nav_qs.values_list('solicitation_number', flat=True))
            idx = sol_numbers.index(sol.solicitation_number)
            for j in range(idx + 1, len(sol_numbers)):
                sn = sol_numbers[j]
                cand = Solicitation.objects.filter(solicitation_number=sn).first()
                if not cand:
                    continue
                q = urllib.parse.urlencode({'list_qs': enc})
                return redirect(
                    f"{reverse('sales:solicitation_detail', args=[sn])}?{q}"
                )
        except (ValueError, Exception):
            pass
        q = urllib.parse.urlencode({'list_qs': enc})
        messages.success(request, 'End of list for current filters.')
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
        sol.status = 'NO_BID'
        _release_review_claim(sol)
        sol.save(update_fields=[
            'status',
            'review_claimed_by', 'review_claimed_at', 'review_claim_expires_at',
        ])
        return _redirect_after_workbench_action(request, sol, list_qs_raw, queue_kind)

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
    Annotates each solicitation with first_line and total_match_count.
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

    raw_tab = request.GET.get('tab', 'matches')
    active_tab = raw_tab if raw_tab in VALID_TABS else 'matches'

    pre_tab = _list_qs_before_tab(request.GET)
    tab_counts = {
        'matches': pre_tab.exclude(status='NO_BID').filter(match_count__gt=0).count(),
        'set_asides': pre_tab.exclude(status='NO_BID').exclude(UNRESTRICTED_TAB_Q).count(),
        'unrestricted': pre_tab.exclude(status='NO_BID').filter(UNRESTRICTED_TAB_Q).count(),
        'research': pre_tab.filter(status='RESEARCH').count(),
    }
    nobid_count = Solicitation.objects.filter(status='NO_BID').count()

    qs = _build_list_queryset(request.GET)
    eligible_for_mass_pass_count = qs.filter(status__in=['New', 'Active']).count()

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

    filter_params = {k: v for k, v in request.GET.items() if k != "page"}
    filter_snapshot = urllib.parse.urlencode(filter_params)
    filter_params_no_tab = {k: v for k, v in request.GET.items() if k not in ("page", "tab")}
    filter_params_no_sort = {k: v for k, v in request.GET.items() if k not in ("page", "sort")}

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
        "status_choices": Solicitation.STATUS_CHOICES,
        "current_filters": {
            "q": q,
            "set_aside": set_aside,
            "status": status,
            "item_type": item_type,
        },
        "active_tab": active_tab,
        "tab_counts": tab_counts,
        "nobid_count": nobid_count,
        "sort_param": sort_param_val,
        "sort_links": sort_links,
        "filter_querystring": urllib.parse.urlencode(filter_params),
        "filter_snapshot": filter_snapshot,
        "filter_querystring_no_tab": urllib.parse.urlencode(filter_params_no_tab),
        "filter_querystring_no_sort": urllib.parse.urlencode(filter_params_no_sort),
        "eligible_for_mass_pass_count": eligible_for_mass_pass_count,
    })


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
    if hist_saved > 0 or pack_saved:
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

    no_quote_cages = get_no_quote_cage_set()
    _rpc = _workbench_procurement_packaging_context(solicitation, line)
    procurement_history = _rpc["procurement_history"]
    packaging = _rpc["packaging"]
    has_pdf_blob = _rpc["has_pdf_blob"]
    supplier_matches = build_consolidated_supplier_list(solicitation, no_quote_cages)
    rfqs_queued = SupplierRFQ.objects.filter(
        line__solicitation=solicitation,
        status="QUEUED",
    ).exists()
    queued_cages = set(
        normalize_cage_code(c)
        for c in SupplierRFQ.objects.filter(
            line__solicitation=solicitation,
            status="QUEUED",
        ).values_list("supplier__cage_code", flat=True)
        if normalize_cage_code(c)
    )

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
            "supplier_matches": supplier_matches,
            "rfqs_queued": rfqs_queued,
            "queued_cages": queued_cages,
            "return_by_urgent": return_by_urgent,
            "nav_record_num": nav_record_num,
            "nav_total": nav_total,
            "workbench_claim_blocked": workbench_claim_blocked,
            "show_triage_actions": show_triage_actions,
            "show_research_button": show_research_button,
        },
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


@login_required
def solicitation_archive(request):
    """
    Read-only mining view for Archived solicitations.
    Paginated at 50 per page, sorted by return_by_date descending.
    """
    qs = (
        Solicitation.objects.filter(status="Archived")
        .select_related("import_batch")
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=SolicitationLine.objects.order_by("line_number", "id"),
            )
        )
        .order_by("-return_by_date")
    )

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

    total_archived = Solicitation.objects.filter(status="Archived").count()

    return render(
        request,
        "sales/solicitations/archive.html",
        {
            "page_obj": page_obj,
            "total_archived": total_archived,
            "filter_querystring": filter_querystring,
            "set_aside_choices": SET_ASIDE_CHOICES,
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

    updated = Solicitation.objects.filter(
        pk__in=sol_ids,
        status__in=safe_statuses,
    ).update(status='NO_BID')

    messages.success(request, f'{updated} solicitation(s) marked No Bid.')
    return redirect('sales:solicitation_list')


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


# URL name `solicitation_detail` still resolves to this view; alias for explicit imports.
solicitation_detail = solicitation_workbench
