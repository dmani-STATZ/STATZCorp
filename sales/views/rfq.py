"""
RFQ dispatch and quote entry views. Section 10.5, 10.8.
"""
from datetime import timedelta
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.contrib import messages
from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone
from django.http import JsonResponse

from sales.models import (
    Solicitation,
    SolicitationLine,
    SupplierMatch,
    SupplierRFQ,
    SupplierQuote,
    SupplierContactLog,
    CompanyCAGE,
    ApprovedSource,
)
from sales.services.email import send_rfq_email, send_followup_email


# ---------- Pending queue: matches with no RFQ sent ----------

@login_required
def rfq_pending(request):
    """
    Shows all SupplierMatch records where no SupplierRFQ has been sent yet,
    grouped by solicitation. Template: sales/rfq/pending.html
    """
    # Matches that have no RFQ for (line, supplier)
    rfq_exists = SupplierRFQ.objects.filter(
        line=OuterRef("line_id"),
        supplier=OuterRef("supplier_id"),
    )
    pending_matches = (
        SupplierMatch.objects.filter(~Exists(rfq_exists))
        .select_related("supplier", "line", "line__solicitation")
        .order_by("line__solicitation__return_by_date", "line__solicitation__solicitation_number", "match_tier", "-match_score")
    )

    # Group by (solicitation, line) — one line per sol for simplicity per spec
    from collections import OrderedDict
    groups = OrderedDict()
    for m in pending_matches:
        sol = m.line.solicitation
        key = (sol.id, m.line.id)
        if key not in groups:
            groups[key] = {
                "solicitation": sol,
                "line": m.line,
                "matches": [],
            }
        groups[key]["matches"].append(m)

    pending_groups = list(groups.values())
    total_pending = len(pending_matches)

    return render(request, "sales/rfq/pending.html", {
        "pending_groups": pending_groups,
        "total_pending": total_pending,
    })


@login_required
@require_POST
def rfq_send_batch(request, sol_number):
    """
    POST: supplier_ids[] or send_all. Create SupplierRFQ (PENDING), call send_rfq_email for each.
    Redirect to rfq_pending with message.
    """
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    send_all = request.POST.get("send_all") == "1" or "send_all" in request.POST.getlist("send_all")
    supplier_ids = request.POST.getlist("supplier_ids[]") or request.POST.getlist("supplier_ids")

    if send_all:
        matches = (
            SupplierMatch.objects.filter(line__solicitation=solicitation)
            .select_related("supplier", "line")
        )
        # Exclude those that already have an RFQ
        existing = set(
            SupplierRFQ.objects.filter(line__solicitation=solicitation).values_list("supplier_id", "line_id")
        )
        matches = [m for m in matches if (m.supplier_id, m.line_id) not in existing]
    else:
        if not supplier_ids:
            messages.warning(request, "No suppliers selected.")
            return redirect("sales:rfq_pending")
        sid_set = {int(x) for x in supplier_ids if str(x).isdigit()}
        matches = list(
            SupplierMatch.objects.filter(
                line__solicitation=solicitation,
                supplier_id__in=sid_set,
            ).select_related("supplier", "line")
        )
        existing = set(
            SupplierRFQ.objects.filter(
                line__solicitation=solicitation,
                supplier_id__in=sid_set,
            ).values_list("supplier_id", "line_id")
        )
        matches = [m for m in matches if (m.supplier_id, m.line_id) not in existing]

    sent = 0
    failed = 0
    for m in matches:
        rfq = SupplierRFQ.objects.create(
            line=m.line,
            supplier=m.supplier,
            status="PENDING",
        )
        if send_rfq_email(rfq, request.user):
            sent += 1
        else:
            failed += 1

    if sent:
        messages.success(request, f"Sent {sent} RFQ(s) for {sol_number}.")
    if failed:
        messages.warning(request, f"{failed} RFQ(s) could not be sent (missing email or error).")
    if not sent and not failed and (send_all or supplier_ids):
        messages.warning(request, "No new RFQs sent (all selected already had an RFQ or no matches).")

    return redirect("sales:rfq_pending")


@login_required
@require_POST
def rfq_send_single(request):
    """POST: match_id. Send RFQ to one supplier for one line. Redirect to pending or referrer."""
    match_id = request.POST.get("match_id")
    if not match_id:
        messages.warning(request, "No match selected.")
        return redirect("sales:rfq_pending")

    match = get_object_or_404(
        SupplierMatch.objects.select_related("supplier", "line", "line__solicitation"),
        pk=match_id,
    )
    if SupplierRFQ.objects.filter(line=match.line, supplier=match.supplier).exists():
        messages.warning(request, "An RFQ was already sent to this supplier for this line.")
    else:
        rfq = SupplierRFQ.objects.create(line=match.line, supplier=match.supplier, status="PENDING")
        if send_rfq_email(rfq, request.user):
            messages.success(request, f"RFQ sent to {match.supplier.name or match.supplier.cage_code}.")
        else:
            messages.warning(request, "Could not send RFQ (missing email or error).")

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("sales:rfq_pending")
    return redirect(next_url)


# ---------- Sent RFQs list ----------

@login_required
def rfq_sent(request):
    """
    Sent RFQs grouped by urgency: overdue, urgent, awaiting, responded, closed.
    Template: sales/rfq/sent.html
    """
    from datetime import timedelta
    from django.utils import timezone

    today = timezone.now().date()
    urgent_cutoff = today + timedelta(days=2)

    base = (
        SupplierRFQ.objects.filter(
            status__in=["SENT", "RESPONDED", "NO_RESPONSE", "DECLINED"]
        )
        .select_related("line__solicitation", "supplier")
    )

    overdue = []
    urgent = []
    awaiting = []
    responded = []
    closed = []

    for rfq in base.order_by("line__solicitation__return_by_date", "sent_at"):
        sol = rfq.line.solicitation
        return_by = sol.return_by_date if sol else None
        if rfq.status == "SENT":
            if return_by and return_by < today:
                overdue.append(rfq)
            elif return_by and return_by <= urgent_cutoff:
                urgent.append(rfq)
            else:
                awaiting.append(rfq)
        elif rfq.status == "RESPONDED":
            responded.append(rfq)
        else:
            closed.append(rfq)

    return render(request, "sales/rfq/sent.html", {
        "overdue": overdue,
        "urgent": urgent,
        "awaiting": awaiting,
        "responded": responded,
        "closed": closed,
    })


# ---------- 3-panel RFQ Center ----------

@login_required
@require_http_methods(["GET"])
def rfq_center(request):
    """
    GET: render the 3-panel RFQ Center shell with left panel populated.
    Context: rfq_groups (overdue, urgent, awaiting, responded, closed), selected_rfq_id, default_markup_pct.
    """
    today = timezone.now().date()
    urgent_cutoff = today + timedelta(days=2)

    base = (
        SupplierRFQ.objects.filter(
            status__in=["SENT", "RESPONDED", "NO_RESPONSE", "DECLINED"]
        )
        .select_related("supplier", "line__solicitation")
        .order_by("line__solicitation__return_by_date", "sent_at")
    )

    overdue = []
    urgent = []
    awaiting = []
    responded = []
    closed = []

    for rfq in base:
        sol = rfq.line.solicitation
        return_by = sol.return_by_date if sol else None
        if rfq.status == "SENT":
            if return_by and return_by < today:
                overdue.append(rfq)
            elif return_by and return_by <= urgent_cutoff:
                urgent.append(rfq)
            else:
                awaiting.append(rfq)
        elif rfq.status == "RESPONDED":
            responded.append(rfq)
        else:
            closed.append(rfq)

    selected_rfq_id = None
    try:
        r = request.GET.get("rfq")
        if r:
            selected_rfq_id = int(r)
    except (ValueError, TypeError):
        pass

    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    default_markup_pct = Decimal(str(cage.default_markup_pct)) if cage else Decimal("3.50")

    rfq_groups_display = [
        ("overdue", "🔴 Overdue", overdue, "#dc2626"),
        ("urgent", "🟠 Urgent ≤2 days", urgent, "#ea580c"),
        ("awaiting", "🟡 Awaiting", awaiting, "#ca8a04"),
        ("responded", "🟢 Responded", responded, "#16a34a"),
        ("closed", "⛌ Closed", closed, "#6b7280"),
    ]

    return render(request, "sales/rfq/center.html", {
        "rfq_groups_display": rfq_groups_display,
        "selected_rfq_id": selected_rfq_id or 0,
        "default_markup_pct": default_markup_pct,
        "today": today,
    })


@login_required
@require_GET
def rfq_center_detail(request, rfq_id):
    """
    Returns the center panel HTML fragment for the selected RFQ (for fetch() from JS).
    Context: rfq, quotes, approved_sources, default_markup_pct, suggested_bid.
    """
    rfq = get_object_or_404(
        SupplierRFQ.objects.select_related("supplier", "line__solicitation").prefetch_related(
            "contact_log", "quotes"
        ),
        pk=rfq_id,
    )
    line = rfq.line
    sol = line.solicitation
    quotes = list(rfq.quotes.all())
    nsn_normalized = (line.nsn or "").replace("-", "").strip()
    approved_sources = list(ApprovedSource.objects.filter(nsn=nsn_normalized)[:20])
    contact_log = list(rfq.contact_log.select_related("logged_by").order_by("-logged_at"))

    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    default_markup_pct = Decimal(str(cage.default_markup_pct)) if cage else Decimal("3.50")
    best_quote = min(quotes, key=lambda q: q.unit_price) if quotes else None
    suggested_bid = (
        (best_quote.unit_price * (1 + default_markup_pct / 100)) if best_quote else None
    )

    return render(request, "sales/rfq/partials/center_panel.html", {
        "rfq": rfq,
        "line": line,
        "solicitation": sol,
        "quotes": quotes,
        "approved_sources": approved_sources,
        "contact_log": contact_log,
        "default_markup_pct": default_markup_pct,
        "suggested_bid": suggested_bid,
    })


@login_required
@require_POST
def rfq_mark_no_response(request, rfq_id):
    """Set rfq.status = NO_RESPONSE, add contact log, redirect to rfq_sent."""
    rfq = get_object_or_404(
        SupplierRFQ.objects.select_related("line__solicitation", "supplier"),
        pk=rfq_id,
    )
    rfq.status = "NO_RESPONSE"
    rfq.save(update_fields=["status"])
    SupplierContactLog.objects.create(
        rfq=rfq,
        supplier=rfq.supplier,
        solicitation=rfq.line.solicitation,
        method="NOTE",
        direction="OUT",
        summary="Marked No Response",
        logged_by=request.user,
    )
    messages.success(request, "Marked as No Response.")
    return redirect("sales:rfq_sent")


@login_required
@require_POST
def rfq_mark_declined(request, rfq_id):
    """POST: declined_reason (optional). Set status=DECLINED, add log, redirect to rfq_sent."""
    rfq = get_object_or_404(
        SupplierRFQ.objects.select_related("line__solicitation", "supplier"),
        pk=rfq_id,
    )
    reason = (request.POST.get("declined_reason") or "").strip()[:255]
    rfq.status = "DECLINED"
    rfq.declined_reason = reason or None
    rfq.save(update_fields=["status", "declined_reason"])
    SupplierContactLog.objects.create(
        rfq=rfq,
        supplier=rfq.supplier,
        solicitation=rfq.line.solicitation,
        method="NOTE",
        direction="OUT",
        summary=f"Marked Declined{f': {reason}' if reason else ''}",
        logged_by=request.user,
    )
    messages.success(request, "Marked as Declined.")
    return redirect("sales:rfq_sent")


@login_required
@require_POST
def rfq_send_followup(request, rfq_id):
    """Call send_followup_email, redirect to rfq_sent with message."""
    rfq = get_object_or_404(SupplierRFQ, pk=rfq_id)
    if send_followup_email(rfq, request.user):
        messages.success(request, "Follow-up email sent.")
    else:
        messages.warning(request, "Could not send follow-up (only SENT RFQs allowed, or email error).")
    return redirect("sales:rfq_sent")


# ---------- Quote entry ----------

class QuoteEntryForm:
    """Minimal form for quote entry: unit_price, lead_time_days, part_number_offered, quantity_available, notes."""

    def __init__(self, data=None, initial=None):
        self.data = data
        self.initial = initial or {}
        self.errors = {}
        self.cleaned_data = {}

    def is_valid(self):
        from django.forms import DecimalField, IntegerField, CharField, ChoiceField
        unit_price = self.data.get("unit_price") if self.data else self.initial.get("unit_price")
        lead_time = self.data.get("lead_time_days") if self.data else self.initial.get("lead_time_days")
        part_number = (self.data or {}).get("part_number_offered", "") or self.initial.get("part_number_offered", "")
        qty_avail = (self.data or {}).get("quantity_available", "") or self.initial.get("quantity_available", "")
        notes = (self.data or {}).get("notes", "") or self.initial.get("notes", "")

        err = {}
        try:
            up = Decimal(str(unit_price).strip()) if unit_price not in (None, "") else None
        except Exception:
            up = None
        if up is None:
            err["unit_price"] = "Required."
        elif up < 0:
            err["unit_price"] = "Must be ≥ 0."
        else:
            self.cleaned_data["unit_price"] = up

        try:
            lt = int(lead_time) if lead_time not in (None, "") else None
        except (ValueError, TypeError):
            lt = None
        if lt is None:
            err["lead_time_days"] = "Required."
        elif lt < 0:
            err["lead_time_days"] = "Must be ≥ 0."
        else:
            self.cleaned_data["lead_time_days"] = lt

        self.cleaned_data["part_number_offered"] = (part_number or "").strip()[:100] or None
        try:
            self.cleaned_data["quantity_available"] = int(qty_avail) if qty_avail not in (None, "") else None
        except (ValueError, TypeError):
            self.cleaned_data["quantity_available"] = None
        self.cleaned_data["notes"] = (notes or "").strip() or None

        self.errors = err
        return len(err) == 0


@login_required
@require_http_methods(["GET", "POST"])
def rfq_enter_quote(request, rfq_id):
    """
    GET: quote entry form. POST: validate, create SupplierQuote, set rfq.status=RESPONDED,
    advance solicitation to QUOTING, contact log, redirect to rfq_sent or ?next=.
    """
    rfq = get_object_or_404(
        SupplierRFQ.objects.select_related("line__solicitation", "supplier"),
        pk=rfq_id,
    )
    line = rfq.line
    sol = line.solicitation
    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    default_markup_pct = float(cage.default_markup_pct) if cage else 3.50

    initial = {
        "lead_time_days": line.delivery_days,
    }

    if request.method == "POST":
        form = QuoteEntryForm(data=request.POST, initial=initial)
        from_center = request.POST.get("from_center") or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        if not form.is_valid():
            if from_center:
                return JsonResponse({"success": False, "errors": form.errors})
        if form.is_valid():
            quote = SupplierQuote.objects.create(
                rfq=rfq,
                line=line,
                supplier=rfq.supplier,
                nsn=line.nsn or "",
                unit_price=form.cleaned_data["unit_price"],
                lead_time_days=form.cleaned_data["lead_time_days"],
                part_number_offered=form.cleaned_data["part_number_offered"],
                quantity_available=form.cleaned_data["quantity_available"],
                notes=form.cleaned_data["notes"],
                entered_by=request.user,
            )
            from django.utils import timezone
            now = timezone.now()
            rfq.status = "RESPONDED"
            rfq.response_received_at = now
            rfq.save(update_fields=["status", "response_received_at"])

            SupplierContactLog.objects.create(
                rfq=rfq,
                supplier=rfq.supplier,
                solicitation=sol,
                method="EMAIL_IN",
                direction="IN",
                summary=f"Quote entered: ${quote.unit_price} / {quote.lead_time_days}d",
                logged_by=request.user,
            )

            if sol.status in ("New", "Matching", "RFQ_PENDING", "RFQ_SENT"):
                sol.status = "QUOTING"
                sol.save(update_fields=["status"])

            suggested = form.cleaned_data["unit_price"] * (1 + default_markup_pct / 100)
            messages.success(request, f"Quote saved — Suggested bid: ${suggested:.5f}")
            if request.POST.get("from_center") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({
                    "success": True,
                    "rfq_id": rfq.pk,
                    "suggested_bid": float(suggested),
                })
            next_url = request.GET.get("next") or request.POST.get("next") or reverse("sales:rfq_sent")
            return redirect(next_url)
    else:
        form = QuoteEntryForm(initial=initial)

    return render(request, "sales/rfq/quote_entry.html", {
        "rfq": rfq,
        "line": line,
        "solicitation": sol,
        "default_markup_pct": default_markup_pct,
        "form": form,
    })


@login_required
@require_POST
def quote_select_for_bid(request, quote_id):
    """POST: set is_selected_for_bid=True on the quote. Redirect to next or sol detail."""
    quote = get_object_or_404(
        SupplierQuote.objects.select_related("line__solicitation"),
        pk=quote_id,
    )
    quote.is_selected_for_bid = True
    quote.save(update_fields=["is_selected_for_bid"])
    messages.success(request, "Quote selected for bid.")
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if not next_url and quote.line and quote.line.solicitation:
        next_url = reverse("sales:solicitation_detail", args=[quote.line.solicitation.solicitation_number])
    return redirect(next_url or reverse("sales:rfq_sent"))
