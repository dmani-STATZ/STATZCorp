"""
Solicitation list and detail views.
"""
import urllib.parse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Count, Prefetch, Q
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
)

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


@login_required
def solicitation_list(request):
    """
    Lists solicitations with filtering and pagination.
    Annotates each solicitation with first_line and total_match_count.
    """
    from django.core.paginator import Paginator
    import datetime

    q           = request.GET.get('q', '').strip()
    set_aside   = request.GET.get('set_aside', '')
    status      = request.GET.get('status', '')
    item_type   = request.GET.get('item_type', '')

    qs = (
        Solicitation.objects
        .prefetch_related(
            Prefetch(
                'lines',
                queryset=SolicitationLine.objects.order_by('line_number', 'id'),
            )
        )
        .annotate(total_match_count=Count('lines__supplier_matches', distinct=True))
        .order_by('return_by_date', 'solicitation_number')
    )

    bucket = request.GET.get("bucket", "")
    if bucket:
        qs = qs.filter(bucket=bucket)
    else:
        qs = qs.exclude(bucket="SKIP")
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
    return render(request, "sales/solicitations/list.html", {
        "page_obj": page_obj,
        "set_aside_choices": SET_ASIDE_CHOICES,
        "status_choices": Solicitation.STATUS_CHOICES,
        "current_filters": {
            "q": q,
            "set_aside": set_aside,
            "status": status,
            "item_type": item_type,
            "bucket": bucket,
        },
        "bucket_filter": bucket,
        "bucket_counts": dict(
            Solicitation.objects.values_list("bucket")
            .annotate(n=Count("id"))
            .values_list("bucket", "n")
        ),
        "filter_querystring": urllib.parse.urlencode(filter_params),
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
    approved_sources = ApprovedSource.objects.filter(nsn=nsn_normalized)

    solicitation.set_aside_display = SET_ASIDE_LABELS.get(
        solicitation.small_business_set_aside or "", ""
    )
    pdf_url = solicitation.dibbs_pdf_url or "#"

    # Annotate each match with rfq status for "Send RFQ" vs badge (reuse rfqs list)
    rfq_by_match_key = {(r.line_id, r.supplier_id): r for r in rfqs}
    for m in matches:
        m.rfq_sent = (m.line_id, m.supplier_id) in rfq_by_match_key
        if m.rfq_sent:
            m.rfq_obj = rfq_by_match_key.get((m.line_id, m.supplier_id))
            m.rfq_status_display = m.rfq_obj.get_status_display() if m.rfq_obj else "Sent"

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
