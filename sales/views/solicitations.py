"""
Solicitation list and detail views.
"""
import urllib.parse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Count, Prefetch, Q, OuterRef, Subquery
from django.http import JsonResponse
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
)
from sales.services.email import resolve_supplier_email
from suppliers.models import Supplier

PIPELINE = [
    ("New", "📥", "New"),
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
VALID_TABS = frozenset({'matches', 'set_asides', 'unrestricted', 'nobid'})

# Sort: valid GET values are field name (asc) or -field (desc). Third click clears (default order).
DEFAULT_ORDER = ('return_by_date', 'solicitation_number')
SORTABLE_FIELDS = frozenset({
    'solicitation_number', 'nsn', 'nomenclature', 'quantity',
    'set_aside', 'return_by_date', 'status', 'match_count',
})


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
    qs = qs.exclude(status='NO_BID')
    if tab == 'matches':
        return qs.filter(match_count__gt=0)
    if tab == 'set_asides':
        return qs.exclude(UNRESTRICTED_TAB_Q)
    if tab == 'unrestricted':
        return qs.filter(UNRESTRICTED_TAB_Q)
    return qs


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
    Used by solicitation_list and solicitation_detail (prev/next nav).
    """
    raw_tab = params.get('tab', 'matches')
    tab = raw_tab if raw_tab in VALID_TABS else 'matches'
    qs = _list_qs_before_tab(params)
    qs = _apply_list_tab_filter(qs, tab)
    qs = _apply_list_sort(qs, params.get('sort', '') or '')
    return qs


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

    from django.core.paginator import Paginator
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
    }
    nobid_count = Solicitation.objects.filter(status='NO_BID').count()

    qs = _build_list_queryset(request.GET)

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
    })


@login_required
def solicitation_detail(request, sol_number):
    """
    Detail page for a single solicitation.
    Supports tabs: overview (default), matches, rfqs, quotes, bid.
    """
    solicitation = get_object_or_404(
        Solicitation.objects.select_related("import_batch").prefetch_related("lines"),
        solicitation_number=sol_number,
    )

    prev_sol = None
    next_sol = None
    list_qs_raw = request.GET.get("list_qs", "")
    if list_qs_raw:
        try:
            list_params = dict(
                urllib.parse.parse_qsl(list_qs_raw, keep_blank_values=True)
            )
            nav_qs = _build_list_queryset(list_params)
            sol_numbers = list(
                nav_qs.values_list("solicitation_number", flat=True)
            )
            current_idx = sol_numbers.index(solicitation.solicitation_number)
            if current_idx > 0:
                prev_sol = sol_numbers[current_idx - 1]
            if current_idx < len(sol_numbers) - 1:
                next_sol = sol_numbers[current_idx + 1]
        except (ValueError, Exception):
            pass

    queued_rfq_count = SupplierRFQ.objects.filter(
        line__solicitation=solicitation,
        status="QUEUED",
    ).count()

    line = solicitation.lines.order_by("line_number", "id").first()
    active_tab = request.GET.get("tab", "overview")

    pipeline_steps = _build_pipeline_steps(solicitation.status)
    matches = (
        SupplierMatch.objects.filter(line__solicitation=solicitation)
        .select_related("supplier")
        .order_by("match_tier", "-match_score")
    )
    match_count = matches.count()

    rfqs_qs = (
        SupplierRFQ.objects.filter(line__solicitation=solicitation)
        .select_related("supplier", "line")
        .prefetch_related("quotes", "contact_log")
    )
    rfqs = list(rfqs_qs)
    rfq_count = len(rfqs)

    quotes_qs = (
        SupplierQuote.objects.filter(line__solicitation=solicitation)
        .select_related("supplier", "rfq")
        .order_by("unit_price")
    )
    quote_count = quotes_qs.count()
    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    default_markup_pct = float(cage.default_markup_pct) if cage else 3.50
    quotes = list(quotes_qs)
    for q in quotes:
        q.suggested_bid = float(q.unit_price) * (1 + default_markup_pct / 100)

    contact_log = (
        SupplierContactLog.objects.filter(solicitation=solicitation)
        .select_related("logged_by", "supplier")
        .order_by("-logged_at")
    )

    nsn_normalized = (line.nsn or "").replace("-", "").strip() if line else ""
    approved_sources = list(ApprovedSource.objects.filter(nsn=nsn_normalized))

    # Annotate each approved source with its matching Supplier (if known to us)
    if approved_sources:
        cage_codes = [src.approved_cage for src in approved_sources if src.approved_cage]
        supplier_by_cage = {
            s.cage_code.strip().upper(): s
            for s in Supplier.objects.filter(cage_code__in=cage_codes)
            if s.cage_code
        }
        for src in approved_sources:
            src.matched_supplier = supplier_by_cage.get(
                (src.approved_cage or "").strip().upper()
            )

    solicitation.set_aside_display = SET_ASIDE_LABELS.get(
        solicitation.small_business_set_aside or "", ""
    )
    pdf_url = solicitation.dibbs_pdf_url or "#"

    # Queued RFQ supplier IDs for this solicitation (Add to Queue button state)
    queued_supplier_ids = set(
        SupplierRFQ.objects.filter(
            line__solicitation=solicitation,
            status="QUEUED",
        ).values_list("supplier_id", flat=True)
    )

    # Annotate each match with rfq status for "Send RFQ" vs badge (reuse rfqs list)
    rfq_by_match_key = {(r.line_id, r.supplier_id): r for r in rfqs}
    for m in matches:
        m.rfq_to_email = resolve_supplier_email(m.supplier) or ""
        m.rfq_sent = (m.line_id, m.supplier_id) in rfq_by_match_key
        if m.rfq_sent:
            m.rfq_obj = rfq_by_match_key.get((m.line_id, m.supplier_id))
            m.rfq_status_display = m.rfq_obj.get_status_display() if m.rfq_obj else "Sent"

    # Bid tab context
    company_cages = CompanyCAGE.objects.filter(is_active=True).order_by("-is_default")
    default_cage_obj = company_cages.filter(is_default=True).first() or company_cages.first()
    existing_bid = (
        GovernmentBid.objects.filter(line=line)
        .select_related("selected_quote__supplier")
        .first()
    ) if line else None
    selected_quote_for_bid = (
        next((q for q in quotes if q.is_selected_for_bid), None) or
        (quotes[0] if quotes else None)
    )
    suggested_bid_price_for_tab = (
        float(selected_quote_for_bid.unit_price) * (1 + default_markup_pct / 100)
        if selected_quote_for_bid else None
    )
    _first_as = approved_sources[0] if approved_sources else None
    if existing_bid:
        bid_iv = {
            "price": existing_bid.unit_price,
            "delivery": existing_bid.delivery_days,
            "cage": existing_bid.quoter_cage,
            "quote_cage": existing_bid.quote_for_cage,
            "type": existing_bid.bid_type_code,
            "fob": existing_bid.fob_point,
            "payment": existing_bid.payment_terms or "",
            "md": existing_bid.manufacturer_dealer,
            "mfg_cage": existing_bid.mfg_source_cage or "",
            "material": existing_bid.material_requirements,
            "hazmat": existing_bid.hazardous_material,
            "remarks": existing_bid.bid_remarks or "",
            "pn_code": existing_bid.part_number_offered_code or "",
            "pn_cage": existing_bid.part_number_offered_cage or "",
            "pn": existing_bid.part_number_offered or "",
        }
    else:
        bid_iv = {
            "price": f"{suggested_bid_price_for_tab:.5f}" if suggested_bid_price_for_tab else "",
            "delivery": selected_quote_for_bid.lead_time_days if selected_quote_for_bid else "",
            "cage": default_cage_obj.cage_code if default_cage_obj else "",
            "quote_cage": default_cage_obj.cage_code if default_cage_obj else "",
            "type": "BI",
            "fob": (default_cage_obj.default_fob_point if default_cage_obj else "D") or "D",
            "payment": (default_cage_obj.default_payment_terms if default_cage_obj else "1") or "1",
            "md": "DD",
            "mfg_cage": (
                (selected_quote_for_bid.supplier.cage_code or "")[:5]
                if selected_quote_for_bid and selected_quote_for_bid.supplier else ""
            ),
            "material": "0",
            "hazmat": "N",
            "remarks": "",
            "pn_code": "",
            "pn_cage": _first_as.approved_cage if _first_as else "",
            "pn": (_first_as.part_number[:40] if _first_as and _first_as.part_number else ""),
        }
    bid_show_pn = bool(line and (line.item_description_indicator or "") in "PBN")

    return render(
        request,
        "sales/solicitations/detail.html",
        {
            "solicitation": solicitation,
            "line": line,
            "active_tab": active_tab,
            "pipeline_steps": pipeline_steps,
            "match_count": match_count,
            "rfq_count": rfq_count,
            "quote_count": quote_count,
            "matches": matches,
            "rfqs": rfqs,
            "quotes": quotes,
            "contact_log": contact_log,
            "approved_sources": approved_sources,
            "pdf_url": pdf_url,
            "company_cages": company_cages,
            "default_cage_obj": default_cage_obj,
            "existing_bid": existing_bid,
            "selected_quote_for_bid": selected_quote_for_bid,
            "suggested_bid_price_for_tab": suggested_bid_price_for_tab,
            "bid_iv": bid_iv,
            "bid_show_pn": bid_show_pn,
            "default_markup_pct": default_markup_pct,
            "queued_supplier_ids": queued_supplier_ids,
            "prev_sol": prev_sol,
            "next_sol": next_sol,
            "list_qs": list_qs_raw,
            "queued_rfq_count": queued_rfq_count,
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
