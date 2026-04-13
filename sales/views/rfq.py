"""
RFQ dispatch and quote entry views. Section 10.5, 10.8.
"""
import html
import json
import logging
import urllib.parse
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.contrib import messages
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string

from contracts.models import Address
from suppliers.models import Supplier

from sales.models import (
    Solicitation,
    SolicitationLine,
    SupplierMatch,
    SupplierRFQ,
    SupplierQuote,
    SupplierContactLog,
    CompanyCAGE,
    ApprovedSource,
    EmailTemplate,
    SupplierNSN,
)
from sales.models.inbox import InboxMessage, InboxMessageRFQLink
from sales.services.email import (
    send_rfq_email,
    send_followup_email,
    resolve_supplier_email,
    resolve_supplier_email_for_send,
    compose_grouped_rfq_email_message,
)
from sales.services.matching import normalize_nsn
from sales.services.graph_inbox import (
    fetch_inbox_messages,
    fetch_message_body,
    mark_message_read,
)
from sales.services.no_quote import get_no_quote_cage_set, normalize_cage_code
from sales.services.suppliers import create_supplier_from_sam, get_or_create_stub_supplier

logger = logging.getLogger(__name__)


def _mark_solicitation_pdf_fetch_pending_if_needed(solicitation: Solicitation) -> None:
    """When a sol is queued for RFQ, flag background PDF fetch if no blob yet."""
    if not solicitation.pdf_blob:
        solicitation.pdf_fetch_status = "PENDING"
        solicitation.save(update_fields=["pdf_fetch_status"])


# ---------- Pending queue: matches with no RFQ sent ----------

@login_required
def rfq_pending(request):
    """Retired: former pending-matches screen now routes to the supplier-grouped RFQ Queue."""
    return redirect("sales:rfq_queue")


@login_required
@require_POST
def rfq_send_batch(request, sol_number):
    """
    POST: supplier_ids[] or send_all. Create SupplierRFQ (PENDING), call send_rfq_email for each.
    Redirect to RFQ queue with message.
    """
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    send_all = request.POST.get("send_all") == "1" or "send_all" in request.POST.getlist("send_all")
    supplier_ids = request.POST.getlist("supplier_ids[]") or request.POST.getlist("supplier_ids")
    # Bulk send (Send All / Send Selected) skips CAGEs on the No Quote list — override is only for per-row queue/send on solicitation detail.
    no_quote_cages = get_no_quote_cage_set()

    def _not_no_quote_match(m):
        cc = normalize_cage_code(m.supplier.cage_code)
        return not cc or cc not in no_quote_cages

    if send_all:
        matches = (
            SupplierMatch.objects.filter(line__solicitation=solicitation)
            .select_related("supplier", "line")
        )
        # Exclude those that already have an RFQ
        existing = set(
            SupplierRFQ.objects.filter(line__solicitation=solicitation).values_list("supplier_id", "line_id")
        )
        matches = [
            m for m in matches
            if (m.supplier_id, m.line_id) not in existing and _not_no_quote_match(m)
        ]
    else:
        if not supplier_ids:
            messages.warning(request, "No suppliers selected.")
            return redirect("sales:rfq_queue")
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
        matches = [
            m for m in matches
            if (m.supplier_id, m.line_id) not in existing and _not_no_quote_match(m)
        ]

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

    return redirect("sales:rfq_queue")


@login_required
@require_POST
def rfq_send_single(request):
    """POST: match_id. Send RFQ to one supplier for one line. Redirect to pending or referrer."""
    match_id = request.POST.get("match_id")
    if not match_id:
        messages.warning(request, "No match selected.")
        return redirect("sales:rfq_queue")

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

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("sales:rfq_queue")
    return redirect(next_url)


@login_required
def rfq_mailto(request, match_id):
    """
    GET /sales/rfq/mailto/<match_id>/
    Returns JSON { mailto_url, to_email, subject, body, missing_email: bool }

    Resolves supplier email using priority:
      1. match.supplier.primary_email
      2. match.supplier.business_email
      3. match.supplier.contact.email

    Renders the default EmailTemplate (or first available) with solicitation variables.
    If no email is found, returns { missing_email: true, mailto_url: null }.
    """
    match = get_object_or_404(
        SupplierMatch.objects.select_related(
            "supplier",
            "supplier__contact",
            "line",
            "line__solicitation",
        ),
        pk=match_id,
    )

    supplier = match.supplier
    line = match.line
    sol = line.solicitation

    # Resolve email address
    to_email = resolve_supplier_email(supplier)

    if not to_email:
        return JsonResponse({"missing_email": True, "mailto_url": None})

    # Build template context
    context = {
        "supplier_name": supplier.name or "",
        "sol_number": sol.solicitation_number or "",
        "nsn": line.nsn or "",
        "nomenclature": line.nomenclature or "",
        "qty": str(line.quantity) if line.quantity is not None else "",
        "unit_of_issue": line.unit_of_issue or "",
        "return_date": sol.return_by_date.strftime("%m/%d/%Y") if sol.return_by_date else "",
        "your_name": request.user.get_full_name() or request.user.username,
        "your_email": request.user.email or "",
    }

    # Get default template
    template = (
        EmailTemplate.objects.filter(is_default=True).first()
        or EmailTemplate.objects.first()
    )

    if not template:
        subject = f"RFQ – {context['sol_number']} / NSN {context['nsn']}"
        body = (
            f"Dear {context['supplier_name']},\n\n"
            f"Please provide a quote for NSN {context['nsn']} "
            f"({context['nomenclature']}), Qty {context['qty']} {context['unit_of_issue']}, "
            f"due {context['return_date']}.\n\n"
            f"Solicitation #: {context['sol_number']}\n\n"
            f"Thank you,\n{context['your_name']}\n{context['your_email']}"
        )
    else:
        subject = template.render_subject(context)
        body = template.render_body(context)

    mailto_url = (
        f"mailto:{urllib.parse.quote(to_email)}"
        f"?subject={urllib.parse.quote(subject)}"
        f"&body={urllib.parse.quote(body)}"
    )

    return JsonResponse({
        "missing_email": False,
        "mailto_url": mailto_url,
        "to_email": to_email,
        "subject": subject,
        "body": body,
    })


@login_required
def rfq_mark_sent(request, match_id):
    """
    POST /sales/rfq/<match_id>/mark-sent/
    Creates (or updates) a SupplierRFQ record for this match with status=SENT.
    Also logs a SupplierContactLog entry (EMAIL_OUT).
    Advances solicitation status to RFQ_SENT if not already past that status.

    Returns JSON { success, rfq_id, sent_at, to_email } for JS to update the UI.

    Idempotent: if an RFQ already exists for this match, updates sent_at + status.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    match = get_object_or_404(
        SupplierMatch.objects.select_related(
            "supplier",
            "supplier__contact",
            "line",
            "line__solicitation",
        ),
        pk=match_id,
    )

    supplier = match.supplier
    line = match.line
    sol = line.solicitation

    # Resolve email (same priority as rfq_mailto)
    to_email = resolve_supplier_email(supplier)

    # Create or update SupplierRFQ
    rfq, created = SupplierRFQ.objects.get_or_create(
        line=line,
        supplier=supplier,
        defaults={
            "sent_at": timezone.now(),
            "sent_by": request.user,
            "email_sent_to": to_email or "",
            "status": "SENT",
        },
    )
    if not created:
        rfq.sent_at = timezone.now()
        rfq.sent_by = request.user
        rfq.email_sent_to = to_email or ""
        rfq.status = "SENT"
        rfq.save(update_fields=["sent_at", "sent_by", "email_sent_to", "status"])

    # Log the outbound contact
    SupplierContactLog.objects.create(
        rfq=rfq,
        supplier=supplier,
        solicitation=sol,
        method="EMAIL_OUT",
        direction="OUT",
        summary=f"RFQ sent via mailto to {to_email or 'unknown'}",
        logged_by=request.user,
    )

    # Advance solicitation status if it's still at New or Matching or RFQ_PENDING
    status_order = ["New", "Active", "Matching", "RFQ_PENDING", "RFQ_SENT", "QUOTING", "BID_READY", "BID_SUBMITTED"]
    current_idx = status_order.index(sol.status) if sol.status in status_order else 0
    rfq_sent_idx = status_order.index("RFQ_SENT")
    if current_idx < rfq_sent_idx:
        sol.status = "RFQ_SENT"
        sol.save(update_fields=["status"])

    return JsonResponse({
        "success": True,
        "rfq_id": rfq.pk,
        "sent_at": rfq.sent_at.strftime("%b %d, %Y %H:%M"),
        "to_email": to_email or "",
        "created": created,
    })


# ---------- Sent RFQs list ----------

@login_required
def rfq_sent(request):
    """
    Sent RFQs grouped by supplier with response status (RESPONDED / AWAITING / OVERDUE).
    Includes READY_TO_SEND rows (shown with a Pending Send badge until Graph send completes).
    Template: sales/rfq/sent.html
    """
    from collections import OrderedDict

    today = timezone.now().date()
    overdue_cutoff = today + timedelta(days=3)

    base = (
        SupplierRFQ.objects.filter(status__in=["SENT", "RESPONDED", "READY_TO_SEND"])
        .select_related("line__solicitation", "supplier")
    )
    rfq_list = list(base.order_by("supplier__name", "line__solicitation__solicitation_number"))

    groups_od = OrderedDict()
    for rfq in rfq_list:
        sid = rfq.supplier_id
        if sid not in groups_od:
            groups_od[sid] = {
                "supplier": rfq.supplier,
                "rfqs": [],
                "sols": [],
                "_sol_ids": set(),
            }
        g = groups_od[sid]
        g["rfqs"].append(rfq)
        sol = rfq.line.solicitation
        if sol.pk not in g["_sol_ids"]:
            g["_sol_ids"].add(sol.pk)
            g["sols"].append(sol)

    supplier_groups = []
    for _sid, g in groups_od.items():
        del g["_sol_ids"]
        rfqs = g["rfqs"]
        times = [r.sent_at for r in rfqs if r.sent_at]
        g["sent_at"] = min(times) if times else None

        rfq_id_list = [r.pk for r in rfqs]
        has_quote = SupplierQuote.objects.filter(rfq_id__in=rfq_id_list).exists()
        has_sent_or_responded = any(r.status in ("SENT", "RESPONDED") for r in rfqs)
        if has_quote:
            g["response_status"] = "RESPONDED"
        elif not has_sent_or_responded:
            g["response_status"] = "AWAITING"
        else:
            urgent_sol = any(
                (sl.return_by_date and sl.return_by_date <= overdue_cutoff)
                for sl in g["sols"]
                if getattr(sl, "return_by_date", None)
            )
            g["response_status"] = "OVERDUE" if urgent_sol else "AWAITING"
        sent_only = [r for r in rfqs if r.status == "SENT"]
        g["followup_rfq"] = sent_only[0] if sent_only else None
        supplier_groups.append(g)

    rank = {"OVERDUE": 0, "AWAITING": 1, "RESPONDED": 2}
    supplier_groups.sort(
        key=lambda x: (rank.get(x["response_status"], 9), (x["supplier"].name or "").lower())
    )

    follow_up_templates = list(EmailTemplate.objects.order_by("name"))

    return render(request, "sales/rfq/sent.html", {
        "supplier_groups": supplier_groups,
        "follow_up_templates": follow_up_templates,
        "today": today,
        "section": "rfq",
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

    queued_count = SupplierRFQ.objects.filter(
        status__in=("QUEUED", "READY_TO_SEND")
    ).count()

    return render(request, "sales/rfq/center.html", {
        "rfq_groups_display": rfq_groups_display,
        "selected_rfq_id": selected_rfq_id or 0,
        "default_markup_pct": default_markup_pct,
        "today": today,
        "queued_count": queued_count,
        "section": "rfq",
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
    """Call send_followup_email (optional EmailTemplate from POST template_id)."""
    rfq = get_object_or_404(SupplierRFQ, pk=rfq_id)
    tpl = None
    tid = request.POST.get("template_id")
    if tid and str(tid).isdigit():
        tpl = EmailTemplate.objects.filter(pk=int(tid)).first()
    if send_followup_email(rfq, request.user, email_template=tpl):
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
            if not SupplierMatch.objects.filter(line=line, supplier=rfq.supplier).exists():
                SupplierMatch.objects.create(
                    line=line,
                    supplier=rfq.supplier,
                    match_method="MANUAL",
                    match_tier=3,
                    match_score=Decimal("0.00"),
                )
            nsn_raw = (line.nsn or "").strip()
            if nsn_raw and rfq.supplier_id:
                n_norm = normalize_nsn(nsn_raw)
                if n_norm:
                    SupplierNSN.objects.get_or_create(
                        supplier_id=rfq.supplier_id,
                        nsn=n_norm,
                        defaults={
                            "notes": "",
                            "added_by": request.user,
                        },
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

            if sol.status in ("New", "Active", "Matching", "RFQ_PENDING", "RFQ_SENT"):
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
        "section": "rfq",
    })


@login_required
def rfq_cage_preview(request):
    """
    GET /sales/rfq/cage-preview/?cage=XXXXX
    Preview-only — no DB writes. Returns SAM.gov entity info + whether the CAGE is
    already in the supplier DB.

    Returns JSON:
    { found, legal_name, registration_status, registration_expiry,
      set_aside_flags, exclusion_status, uei, address, already_in_db,
      existing_supplier_id }
    OR { found: false, error, no_api_key }
    """
    from sales.services.sam_entity import lookup_cage
    from suppliers.models import Supplier as _Supplier
    from django.core.exceptions import ImproperlyConfigured
    import requests as _requests

    cage = request.GET.get('cage', '').strip().upper()
    if not cage:
        return JsonResponse({'found': False, 'error': 'CAGE code required.'})

    existing = _Supplier.objects.filter(cage_code=cage).first()

    try:
        sam = lookup_cage(cage)
    except ImproperlyConfigured:
        if existing:
            return JsonResponse({
                'found': True,
                'legal_name': existing.name,
                'registration_status': 'Unknown (no SAM API key)',
                'already_in_db': True,
                'existing_supplier_id': existing.pk,
            })
        return JsonResponse({
            'found': False,
            'error': 'SAM.gov API key not configured. Enter details manually.',
            'no_api_key': True,
        })
    except _requests.RequestException as e:
        return JsonResponse({'found': False, 'error': f'SAM.gov error: {e}'})

    if not sam.get('found'):
        return JsonResponse({'found': False, 'error': f'CAGE {cage} not found on SAM.gov.'})

    return JsonResponse({
        'found': True,
        'legal_name':           sam['legal_name'],
        'registration_status':  sam.get('registration_status', ''),
        'registration_expiry':  sam.get('registration_expiry', ''),
        'set_aside_flags':      sam.get('set_aside_flags', {}),
        'exclusion_status':     sam.get('exclusion_status', ''),
        'uei':                  sam.get('uei', ''),
        'address':              sam.get('address', {}),
        'already_in_db':        bool(existing),
        'existing_supplier_id': existing.pk if existing else None,
    })


def _build_mailto_for_supplier(supplier, line, user):
    """
    Shared helper: build a mailto URL using the default EmailTemplate.
    Returns (mailto_url, to_email) or (None, None) if no email found.
    """
    to_email = resolve_supplier_email(supplier)

    if not to_email:
        return (None, None)

    sol = line.solicitation
    context = {
        'supplier_name': supplier.name or '',
        'sol_number': sol.solicitation_number or '',
        'nsn': line.nsn or '',
        'nomenclature': line.nomenclature or '',
        'qty': str(line.quantity) if line.quantity is not None else '',
        'unit_of_issue': line.unit_of_issue or '',
        'return_date': sol.return_by_date.strftime('%m/%d/%Y') if sol.return_by_date else '',
        'your_name': user.get_full_name() or user.username,
        'your_email': user.email or '',
    }

    template = (
        EmailTemplate.objects.filter(is_default=True).first()
        or EmailTemplate.objects.first()
    )
    if template:
        subject = template.render_subject(context)
        body = template.render_body(context)
    else:
        subject = f"RFQ – {context['sol_number']} / NSN {context['nsn']}"
        body = (
            f"Dear {context['supplier_name']},\n\n"
            f"Please provide a quote for NSN {context['nsn']} "
            f"({context['nomenclature']}), Qty {context['qty']} {context['unit_of_issue']}, "
            f"due {context['return_date']}.\n\nSolicitation #: {context['sol_number']}\n\n"
            f"Thank you,\n{context['your_name']}\n{context['your_email']}"
        )

    mailto_url = (
        f"mailto:{urllib.parse.quote(to_email)}"
        f"?subject={urllib.parse.quote(subject)}"
        f"&body={urllib.parse.quote(body)}"
    )
    return (mailto_url, to_email)


@login_required
@require_POST
def rfq_send_to_approved_source(request):
    """
    POST /sales/rfq/send-to-approved-source/
    Params: approved_source_id, line_id, email (optional)

    Auto-creates a Supplier from SAM.gov (or falls back to stub), creates a
    SupplierMatch (tier 2, APPROVED_SOURCE), and returns a mailto URL.
    """
    from sales.services.sam_entity import lookup_cage
    from django.core.exceptions import ImproperlyConfigured
    import requests as _requests

    approved_source_id = request.POST.get('approved_source_id')
    line_id = request.POST.get('line_id')
    email_param = (request.POST.get('email') or '').strip()

    if not approved_source_id or not line_id:
        return JsonResponse({'success': False, 'error': 'Missing required parameters.'}, status=400)

    source = get_object_or_404(ApprovedSource, pk=approved_source_id)
    line = get_object_or_404(SolicitationLine.objects.select_related('solicitation'), pk=line_id)

    cage = (source.approved_cage or '').strip().upper()
    company_name = source.company_name or ''

    from suppliers.models import Supplier as _Supplier
    supplier = _Supplier.objects.filter(cage_code=cage).first() if cage else None

    was_created = False
    from_sam = False

    if not supplier:
        try:
            sam = lookup_cage(cage) if cage else {'found': False}
            if sam.get('found'):
                supplier, was_created = create_supplier_from_sam(sam, email=email_param)
                from_sam = True
            else:
                supplier, was_created = get_or_create_stub_supplier(cage, company_name, email_param)
        except (ImproperlyConfigured, _requests.RequestException):
            supplier, was_created = get_or_create_stub_supplier(cage, company_name, email_param)

    match, _ = SupplierMatch.objects.get_or_create(
        line=line,
        supplier=supplier,
        defaults={'match_tier': 2, 'match_method': 'APPROVED_SOURCE', 'match_score': 0},
    )

    # If email_param provided and supplier has no email yet, set it
    if email_param and not (supplier.primary_email or supplier.business_email):
        supplier.business_email = email_param
        supplier.save(update_fields=['business_email'])

    mailto_url, to_email = _build_mailto_for_supplier(supplier, line, request.user)

    if not to_email:
        return JsonResponse({'success': False, 'needs_email': True, 'match_id': match.pk})

    return JsonResponse({
        'success': True,
        'match_id': match.pk,
        'mailto_url': mailto_url,
        'to_email': to_email,
        'supplier_name': supplier.name or cage,
        'was_created': was_created,
        'from_sam': from_sam,
        'cage': cage,
    })


@login_required
@require_POST
def rfq_send_to_adhoc(request):
    """
    POST /sales/rfq/send-to-adhoc/
    Params: line_id, cage (required), email (optional override)
    Fallback params (when SAM fails): name, email (both required)

    Looks up CAGE on SAM.gov, creates Supplier, creates SupplierMatch (tier 4,
    MANUAL), returns mailto URL.
    """
    from sales.services.sam_entity import lookup_cage
    from django.core.exceptions import ImproperlyConfigured
    import requests as _requests

    line_id = request.POST.get('line_id')
    cage = (request.POST.get('cage') or '').strip().upper()
    email_param = (request.POST.get('email') or '').strip()
    name_param = (request.POST.get('name') or '').strip()

    if not line_id or not cage:
        return JsonResponse({'success': False, 'error': 'line_id and cage are required.'}, status=400)

    line = get_object_or_404(SolicitationLine.objects.select_related('solicitation'), pk=line_id)

    supplier = None
    was_created = False
    from_sam = False

    try:
        sam = lookup_cage(cage)
        if sam.get('found'):
            supplier, was_created = create_supplier_from_sam(sam, email=email_param)
            from_sam = True
        else:
            if name_param and email_param:
                supplier, was_created = get_or_create_stub_supplier(cage, name_param, email_param)
            else:
                return JsonResponse({
                    'success': False,
                    'needs_manual': True,
                    'error': f'CAGE {cage} not found on SAM.gov. Enter supplier name and email manually.',
                })
    except ImproperlyConfigured:
        if name_param and email_param:
            supplier, was_created = get_or_create_stub_supplier(cage, name_param, email_param)
        else:
            return JsonResponse({
                'success': False,
                'needs_manual': True,
                'error': 'SAM.gov API key not configured. Enter supplier name and email manually.',
            })
    except _requests.RequestException as e:
        if name_param and email_param:
            supplier, was_created = get_or_create_stub_supplier(cage, name_param, email_param)
        else:
            return JsonResponse({
                'success': False,
                'needs_manual': True,
                'error': f'SAM.gov lookup failed: {e}. Enter supplier name and email manually.',
            })

    match, _ = SupplierMatch.objects.get_or_create(
        line=line,
        supplier=supplier,
        defaults={'match_tier': 4, 'match_method': 'MANUAL', 'match_score': 0},
    )

    # If email_param provided and supplier has no email yet, set it
    if email_param and not (supplier.primary_email or supplier.business_email):
        supplier.business_email = email_param
        supplier.save(update_fields=['business_email'])

    mailto_url, to_email = _build_mailto_for_supplier(supplier, line, request.user)

    if not to_email:
        return JsonResponse({'success': False, 'needs_email': True, 'match_id': match.pk,
                             'error': 'No email address available for this supplier.'})

    return JsonResponse({
        'success': True,
        'match_id': match.pk,
        'mailto_url': mailto_url,
        'to_email': to_email,
        'supplier_name': supplier.name or cage,
        'was_created': was_created,
        'from_sam': from_sam,
        'cage': cage,
    })


@login_required
def rfq_supplier_search(request):
    """
    GET /sales/rfq/supplier-search/?q=<term>&line_id=<id>
    Live search against the supplier database for the ad-hoc RFQ panel.
    """
    from django.db.models import Q
    from suppliers.models import Supplier

    q       = request.GET.get('q', '').strip()
    line_id = request.GET.get('line_id', '')

    if len(q) < 2:
        return JsonResponse({'results': []})

    # Match suppliers dashboard / supplier search: search all suppliers (do not exclude archived)
    qs = Supplier.objects.filter(
        Q(name__icontains=q) | Q(cage_code__icontains=q),
    ).select_related('contact').order_by('name')[:15]

    existing_match_supplier_ids = set()
    if line_id:
        existing_match_supplier_ids = set(
            SupplierMatch.objects.filter(line_id=line_id)
            .values_list('supplier_id', flat=True)
        )

    results = []
    for s in qs:
        email = resolve_supplier_email(s) or ''

        results.append({
            'id':              s.pk,
            'name':            s.name or '',
            'cage_code':       s.cage_code or '',
            'email':           email,
            'has_email':       bool(email),
            'flags': {
                'probation':   getattr(s, 'probation', False),
                'conditional': getattr(s, 'conditional', False),
                'archived':    getattr(s, 'archived', False),
            },
            'already_matched': s.pk in existing_match_supplier_ids,
        })

    return JsonResponse({'results': results})


@login_required
@require_POST
def rfq_send_to_existing(request):
    """
    POST /sales/rfq/send-to-existing/
    Pick an existing Supplier by pk and send them an RFQ for a line.
    """
    from suppliers.models import Supplier

    supplier_id    = request.POST.get('supplier_id')
    line_id        = request.POST.get('line_id')
    email_override = (request.POST.get('email_override') or '').strip()

    if not supplier_id or not line_id:
        return JsonResponse({'success': False, 'error': 'supplier_id and line_id are required.'}, status=400)

    try:
        supplier = Supplier.objects.select_related('contact').get(pk=supplier_id)
    except Supplier.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Supplier not found.'}, status=404)

    line = get_object_or_404(SolicitationLine.objects.select_related('solicitation'), pk=line_id)

    match, _ = SupplierMatch.objects.get_or_create(
        line=line,
        supplier=supplier,
        defaults={'match_tier': 4, 'match_method': 'MANUAL', 'match_score': 0},
    )

    # Apply email override if supplier has no email on file
    if email_override and not resolve_supplier_email(supplier):
        supplier.business_email = email_override
        supplier.save(update_fields=['business_email'])

    mailto_url, to_email = _build_mailto_for_supplier(supplier, line, request.user)

    if not to_email:
        return JsonResponse({'success': False, 'needs_email': True, 'match_id': match.pk,
                             'error': 'No email address available for this supplier.'})

    return JsonResponse({
        'success':       True,
        'match_id':      match.pk,
        'mailto_url':    mailto_url,
        'to_email':      to_email,
        'supplier_name': supplier.name or '',
        'has_email':     True,
        'was_created':   False,
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


# ──────────────────────────────────────────────
# RFQ Queue views (grouped add / fetch PDFs / send)
# ──────────────────────────────────────────────


@login_required
@require_GET
def rfq_manual_supplier_search(request):
    """
    Manual supplier typeahead for solicitation workbench.

    GET ?q= (min 2 chars), optional ?solicitation_number= to exclude suppliers
    that already have a SupplierRFQ on that solicitation (any line).

    HTMX (HX-Request): HTML fragment for #wb-manual-results.
    Otherwise: JSON array [{id, name, cage}].
    """
    q = request.GET.get("q", "").strip()
    sol_key = (request.GET.get("solicitation_number") or request.GET.get("sol_number") or "").strip()
    is_htmx = request.headers.get("HX-Request") == "true"

    if len(q) < 2:
        if is_htmx:
            return render(
                request,
                "sales/solicitations/partials/manual_supplier_search_results.html",
                {"results": [], "solicitation_number": sol_key},
            )
        return JsonResponse([], safe=False)

    suppliers = Supplier.objects.filter(
        Q(name__icontains=q) | Q(cage_code__icontains=q)
    ).order_by("name")
    if sol_key:
        existing = SupplierRFQ.objects.filter(
            line__solicitation__solicitation_number=sol_key,
        ).values_list("supplier_id", flat=True)
        suppliers = suppliers.exclude(pk__in=existing)
    suppliers = suppliers[:20]

    results = [
        {"id": s.pk, "name": s.name or "", "cage": s.cage_code or ""}
        for s in suppliers
    ]

    if is_htmx:
        return render(
            request,
            "sales/solicitations/partials/manual_supplier_search_results.html",
            {
                "results": results,
                "solicitation_number": sol_key,
            },
        )
    return JsonResponse(results, safe=False)


@login_required
@require_POST
def rfq_queue_add_manual(request):
    """
    POST: supplier_id, solicitation_number (or sol_number).

    Creates SupplierRFQ(QUEUED); advances solicitation New/Active/Matching → RFQ_PENDING;
    flags PDF fetch when blob missing. Does not create SupplierMatch (deferred to quote entry).

    HTMX: out-of-band refresh of #wb-matches-sidebar + #wb-manual-results.
    """
    from sales.views.solicitations import _workbench_sidebar_context

    supplier_id = request.POST.get("supplier_id")
    sol_number = (
        request.POST.get("solicitation_number") or request.POST.get("sol_number") or ""
    ).strip()
    is_htmx = request.headers.get("HX-Request") == "true"

    def _htmx_msg(msg: str) -> HttpResponse:
        html = render_to_string(
            "sales/solicitations/partials/manual_queue_htmx_response.html",
            {"htmx_error": msg, "sidebar_inner": ""},
            request=request,
        )
        return HttpResponse(html, content_type="text/html")

    if not supplier_id or not sol_number:
        if is_htmx:
            return _htmx_msg("supplier_id and solicitation_number are required.")
        return JsonResponse(
            {"error": "supplier_id and solicitation_number are required."},
            status=400,
        )

    try:
        sid = int(supplier_id)
    except (ValueError, TypeError):
        if is_htmx:
            return _htmx_msg("Invalid supplier_id.")
        return JsonResponse({"error": "Invalid supplier_id."}, status=400)

    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    line = solicitation.lines.order_by("line_number", "id").first()
    if not line:
        if is_htmx:
            return _htmx_msg("Solicitation has no lines.")
        return JsonResponse({"error": "Solicitation has no lines."}, status=400)

    supplier = get_object_or_404(Supplier, pk=sid)

    cage_norm = normalize_cage_code(supplier.cage_code)
    if cage_norm and cage_norm in get_no_quote_cage_set():
        if is_htmx:
            return _htmx_msg("No Quote CAGE")
        return JsonResponse({"error": "No Quote CAGE"}, status=409)

    if SupplierRFQ.objects.filter(
        line__solicitation=solicitation, supplier=supplier
    ).exists():
        msg = "An RFQ already exists for this supplier on this solicitation."
        if is_htmx:
            return _htmx_msg(msg)
        return JsonResponse({"error": msg}, status=409)

    with transaction.atomic():
        rfq = SupplierRFQ.objects.create(
            line=line,
            supplier=supplier,
            status="QUEUED",
            sent_by=request.user,
        )

        if solicitation.status in ("New", "Active", "Matching"):
            solicitation.status = "RFQ_PENDING"
            solicitation.save(update_fields=["status"])

        _mark_solicitation_pdf_fetch_pending_if_needed(solicitation)

    if is_htmx:
        sidebar_inner = render_to_string(
            "sales/solicitations/partials/workbench_sidebar_matches.html",
            _workbench_sidebar_context(solicitation),
            request=request,
        )
        html = render_to_string(
            "sales/solicitations/partials/manual_queue_htmx_response.html",
            {"htmx_error": None, "sidebar_inner": sidebar_inner},
            request=request,
        )
        return HttpResponse(html, content_type="text/html")

    return JsonResponse(
        {
            "success": True,
            "supplier_id": supplier.pk,
            "supplier_name": supplier.name or "",
            "cage": supplier.cage_code or "",
            "rfq_id": rfq.pk,
        }
    )


@login_required
@require_POST
def rfq_queue_add(request):
    """
    POST: supplier_id, sol_number.
    Create SupplierRFQ(status='QUEUED') for first line of solicitation.
    Advance solicitation to RFQ_PENDING if New/Matching.
    Return JSON { status: 'queued'|'already_queued', rfq_id?: int }.
    """
    supplier_id = request.POST.get("supplier_id")
    sol_number = (request.POST.get("sol_number") or "").strip()
    if not supplier_id or not sol_number:
        return JsonResponse({"status": "error", "error": "supplier_id and sol_number required"}, status=400)

    try:
        sid = int(supplier_id)
    except (ValueError, TypeError):
        return JsonResponse({"status": "error", "error": "invalid supplier_id"}, status=400)

    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    line = solicitation.lines.order_by("line_number", "id").first()
    if not line:
        return JsonResponse({"status": "error", "error": "solicitation has no lines"}, status=400)

    supplier = get_object_or_404(Supplier, pk=sid)
    cage_norm = normalize_cage_code(supplier.cage_code)
    force_nq = request.POST.get("force_no_quote") == "1"
    if cage_norm and cage_norm in get_no_quote_cage_set() and not force_nq:
        return JsonResponse({"status": "no_quote", "cage": cage_norm})

    if SupplierRFQ.objects.filter(
        line=line,
        supplier=supplier,
        status__in=("QUEUED", "READY_TO_SEND"),
    ).exists():
        cur_status = (
            Solicitation.objects.filter(pk=solicitation.pk)
            .values_list("status", flat=True)
            .first()
        ) or ""
        return JsonResponse({
            "status": "already_queued",
            "solicitation_status": cur_status,
        })

    rfq = SupplierRFQ.objects.create(
        line=line,
        supplier=supplier,
        status="QUEUED",
        sent_by=request.user,
    )

    if solicitation.status in ("New", "Active", "Matching"):
        solicitation.status = "RFQ_PENDING"
        solicitation.save(update_fields=["status"])

    _mark_solicitation_pdf_fetch_pending_if_needed(solicitation)

    return JsonResponse({
        "status": "queued",
        "rfq_id": rfq.pk,
        "solicitation_status": solicitation.status,
    })


@login_required
@require_POST
def supplier_create_and_queue(request):
    """
    POST: cage_code, name, sol_number (required); rfq_email, website_url,
    phys_address_line_1/2, phys_city, phys_state, phys_zip (optional).

    Creates or reuses a non-archived Supplier by CAGE, then queues SupplierRFQ
    for the solicitation's first line. Advances solicitation New/Matching → RFQ_PENDING.
    """
    cage_code = (request.POST.get("cage_code") or "").strip().upper()
    name = (request.POST.get("name") or "").strip()
    sol_number = (request.POST.get("sol_number") or "").strip()
    rfq_email = (request.POST.get("rfq_email") or "").strip() or None
    website_url = (request.POST.get("website_url") or "").strip() or None

    phys1 = (request.POST.get("phys_address_line_1") or "").strip() or None
    phys2 = (request.POST.get("phys_address_line_2") or "").strip() or None
    phys_city = (request.POST.get("phys_city") or "").strip() or None
    phys_state = (request.POST.get("phys_state") or "").strip() or None
    phys_zip = (request.POST.get("phys_zip") or "").strip() or None

    if not cage_code or not name or not sol_number:
        return JsonResponse(
            {
                "success": False,
                "error": "CAGE code, company name, and solicitation number are required.",
            }
        )

    cage_norm = normalize_cage_code(cage_code)
    force_nq = request.POST.get("force_no_quote") == "1"
    if cage_norm and cage_norm in get_no_quote_cage_set() and not force_nq:
        return JsonResponse(
            {
                "success": False,
                "error": "no_quote",
                "message": f"CAGE {cage_norm} is on the No Quote list.",
            }
        )

    try:
        with transaction.atomic():
            solicitation = (
                Solicitation.objects.select_for_update()
                .filter(solicitation_number=sol_number)
                .first()
            )
            if not solicitation:
                return JsonResponse({"success": False, "error": "Solicitation not found."})

            line = solicitation.lines.order_by("line_number", "id").first()
            if not line:
                return JsonResponse({"success": False, "error": "Solicitation has no lines."})

            supplier = Supplier.objects.filter(
                archived=False, cage_code__iexact=cage_code
            ).first()
            created_new = False

            if supplier:
                update_fields = []
                if rfq_email:
                    supplier.rfq_email = rfq_email
                    update_fields.append("rfq_email")
                if website_url:
                    supplier.website_url = website_url
                    update_fields.append("website_url")
                if update_fields:
                    supplier.modified_by = request.user
                    update_fields.append("modified_by")
                    supplier.save(update_fields=update_fields)
            else:
                physical = None
                if phys1 or phys2 or phys_city or phys_state or phys_zip:
                    physical = Address.objects.create(
                        address_line_1=phys1,
                        address_line_2=phys2,
                        city=phys_city,
                        state=phys_state,
                        zip=phys_zip,
                    )
                supplier = Supplier.objects.create(
                    name=name,
                    cage_code=cage_code,
                    website_url=website_url,
                    rfq_email=rfq_email,
                    physical_address=physical,
                    archived=False,
                    probation=False,
                    conditional=False,
                    created_by=request.user,
                    modified_by=request.user,
                )
                created_new = True

            existing_q = SupplierRFQ.objects.filter(
                line=line,
                supplier=supplier,
                status__in=("QUEUED", "READY_TO_SEND"),
            ).first()
            if existing_q:
                return JsonResponse(
                    {
                        "success": True,
                        "supplier_id": supplier.pk,
                        "rfq_id": existing_q.pk,
                    }
                )

            rfq = SupplierRFQ.objects.create(
                line=line,
                supplier=supplier,
                status="QUEUED",
                sent_by=request.user,
            )

            if solicitation.status in ("New", "Active", "Matching"):
                solicitation.status = "RFQ_PENDING"
                solicitation.save(update_fields=["status"])

            _mark_solicitation_pdf_fetch_pending_if_needed(solicitation)

            summary = (
                "Supplier created from SAM data and added to RFQ queue"
                if created_new
                else "Existing supplier added to RFQ queue (approved source)"
            )
            SupplierContactLog.objects.create(
                rfq=rfq,
                supplier=supplier,
                solicitation=solicitation,
                method="NOTE",
                direction="OUT",
                summary=summary,
                logged_by=request.user,
            )

        return JsonResponse(
            {"success": True, "supplier_id": supplier.pk, "rfq_id": rfq.pk}
        )
    except Exception:
        logger.exception("supplier_create_and_queue failed")
        return JsonResponse(
            {"success": False, "error": "Could not save supplier. Please try again."},
        )


def _resolve_send_email(supplier):
    """Resolve send email for queue: rfq_email -> business -> primary -> first contact."""
    return resolve_supplier_email_for_send(supplier)


def _rfq_queue_template_context():
    """Shared context for `sales/rfq/queue.html` (QUEUED-only RFQs grouped by supplier)."""
    from collections import OrderedDict

    qs = (
        SupplierRFQ.objects.filter(status="QUEUED")
        .select_related("supplier", "line", "line__solicitation")
        .prefetch_related("supplier__contacts")
        .order_by("supplier__name", "line__solicitation__solicitation_number")
    )
    rfq_list = list(qs)
    nq_set = get_no_quote_cage_set()

    groups = OrderedDict()
    for rfq in rfq_list:
        sid = rfq.supplier_id
        if sid not in groups:
            sup = rfq.supplier
            send_email = _resolve_send_email(sup) or ""
            cc_norm = normalize_cage_code(sup.cage_code or "")
            groups[sid] = {
                "supplier": sup,
                "rfqs": [],
                "sols": [],
                "_sol_ids": set(),
                "email": send_email,
                "send_email": send_email,
                "notes": sup.notes or "",
                "personalization_text": "",
                "has_missing_pdfs": False,
                "is_no_quote": bool(cc_norm and cc_norm in nq_set),
                "awaiting_send": False,
                "has_queued": False,
            }
        g = groups[sid]
        g["rfqs"].append(rfq)
        sol = rfq.line.solicitation
        if sol.pk not in g["_sol_ids"]:
            g["_sol_ids"].add(sol.pk)
            g["sols"].append(sol)
        if not getattr(sol, "pdf_blob", None) or not sol.pdf_blob:
            g["has_missing_pdfs"] = True

    grouped_queue = []
    for sid in sorted(groups.keys(), key=lambda k: (groups[k]["supplier"].name or "").lower()):
        g = groups[sid]
        del g["_sol_ids"]
        if g["rfqs"]:
            g["personalization_text"] = (g["rfqs"][0].personalization_text or "").strip()
        g["awaiting_send"] = False
        g["has_queued"] = bool(g["rfqs"])
        grouped_queue.append(g)

    total_queued_sols = len({r.line.solicitation_id for r in rfq_list})
    today = timezone.now().date()
    return {
        "grouped_queue": grouped_queue,
        "total_queued": len(rfq_list),
        "total_queued_suppliers": len(grouped_queue),
        "total_queued_sols": total_queued_sols,
        "today": today,
    }


@login_required
@require_POST
def rfq_queue_delete_item(request, rfq_id):
    """
    POST /sales/rfq/queue/delete/<rfq_id>/
    Remove one QUEUED SupplierRFQ; optionally revert solicitation from RFQ_PENDING to Active
    when no QUEUED or READY_TO_SEND rows remain for that solicitation.
    """
    rfq = get_object_or_404(
        SupplierRFQ.objects.select_related("line__solicitation"),
        pk=rfq_id,
    )
    if rfq.status != "QUEUED":
        return JsonResponse(
            {"success": False, "error": "Only QUEUED items can be removed"},
            status=400,
        )
    sol = rfq.line.solicitation
    sol_number = sol.solicitation_number or ""
    sol_reverted = False
    with transaction.atomic():
        rfq.delete()
        remaining = SupplierRFQ.objects.filter(
            line__solicitation=sol,
            status__in=("QUEUED", "READY_TO_SEND"),
        ).count()
        if remaining == 0 and sol.status == "RFQ_PENDING":
            sol.status = "Active"
            sol.save(update_fields=["status"])
            sol_reverted = True
    return JsonResponse(
        {
            "success": True,
            "rfq_id": rfq_id,
            "sol_reverted": sol_reverted,
            "sol_number": sol_number,
        }
    )


@login_required
def rfq_queue(request):
    """
    Supplier-grouped RFQ Queue. GET: render. POST: mass send for selected CAGEs.
    """
    if request.method == "POST":
        selected_cages = request.POST.getlist("selected_cages")
        if not selected_cages:
            messages.warning(request, "No suppliers selected.")
            return redirect("sales:rfq_queue")

        no_quote_cages = get_no_quote_cage_set()
        approved_rfq_total = 0

        for cage_raw in selected_cages:
            cage = (cage_raw or "").strip()
            if not cage:
                continue
            cage_norm = normalize_cage_code(cage)
            if cage_norm and cage_norm in no_quote_cages:
                continue
            supplier = Supplier.objects.filter(cage_code__iexact=cage).first()
            if not supplier:
                continue
            rfqs = list(
                SupplierRFQ.objects.filter(
                    status__in=("QUEUED", "READY_TO_SEND"),
                    supplier=supplier,
                ).select_related("line__solicitation")
            )
            if not rfqs or not any(r.status == "QUEUED" for r in rfqs):
                continue

            pers = (request.POST.get(f"personalization_{supplier.pk}") or "").strip()
            send_email = _resolve_send_email(supplier)
            if not send_email:
                name = (supplier.name or supplier.cage_code or f"Supplier {supplier.pk}").strip()
                messages.warning(
                    request,
                    f"Skipped {name}: no email address on file.",
                )
                continue

            approved_here = 0
            for r in rfqs:
                r.personalization_text = pers
                uf = ["personalization_text"]
                if r.status == "QUEUED":
                    r.status = "READY_TO_SEND"
                    uf.append("status")
                    approved_here += 1
                r.save(update_fields=uf)
            approved_rfq_total += approved_here

        if approved_rfq_total == 0:
            messages.warning(request, "No queued RFQs for the selected suppliers.")
            return redirect("sales:rfq_queue")

        messages.success(
            request,
            f"{approved_rfq_total} RFQ(s) approved for send — emails will go out within 15 minutes.",
        )
        return redirect("sales:rfq_queue")

    ctx = _rfq_queue_template_context()
    ctx.setdefault("show_mailto_confirm", False)
    ctx.setdefault("mailto_results", [])
    ctx["section"] = "rfq"
    return render(request, "sales/rfq/queue.html", ctx)


@login_required
@require_POST
def rfq_update_supplier_email(request):
    """Update supplier RFQ email from the queue (stored on ``Supplier.rfq_email``)."""
    cage_code = (request.POST.get("cage_code") or "").strip()
    email = (request.POST.get("email") or "").strip()
    if not cage_code:
        return JsonResponse({"success": False, "error": "CAGE required"}, status=400)
    try:
        supplier = Supplier.objects.get(cage_code__iexact=cage_code)
        supplier.rfq_email = email or None
        supplier.save(update_fields=["rfq_email"])
        return JsonResponse({"success": True})
    except Supplier.DoesNotExist:
        return JsonResponse({"success": False, "error": "Supplier not found"}, status=404)


@login_required
@require_GET
def rfq_supplier_email_options(request, cage_code):
    """
    JSON list of deduplicated email choices for the RFQ email modal (queue).
    GET /sales/rfq/queue/supplier-emails/<cage_code>/
    """
    cage = (cage_code or "").strip()
    supplier = (
        Supplier.objects.filter(cage_code__iexact=cage)
        .prefetch_related("contacts")
        .first()
    )
    if not supplier:
        return JsonResponse({"error": "Supplier not found"}, status=404)

    seen = set()
    options = []

    def add_option(email, label):
        e = (email or "").strip()
        if not e:
            return
        key = e.lower()
        if key in seen:
            return
        seen.add(key)
        options.append({"email": e, "label": label})

    add_option(getattr(supplier, "rfq_email", None), "RFQ Email")
    add_option(getattr(supplier, "primary_email", None), "Primary Email")
    add_option(getattr(supplier, "business_email", None), "Business Email")
    for c in supplier.contacts.all().order_by("name"):
        nm = (c.name or "").strip() or "Contact"
        add_option(getattr(c, "email", None), f"Contact: {nm}")

    return JsonResponse(
        {
            "supplier_name": (supplier.name or "").strip(),
            "options": options,
        }
    )


@login_required
@require_GET
def rfq_preview_email(request, cage_code):
    """JSON preview of grouped RFQ email body for one supplier (QUEUED RFQs)."""
    cage = (cage_code or "").strip()
    supplier = Supplier.objects.filter(cage_code__iexact=cage).first()
    if not supplier:
        return JsonResponse({"error": "Supplier not found"}, status=404)

    rfqs = list(
        SupplierRFQ.objects.filter(
            status__in=("QUEUED", "READY_TO_SEND"),
            supplier=supplier,
        )
        .select_related("line", "line__solicitation", "supplier")
        .prefetch_related("supplier__contacts")
        .order_by("line__solicitation__solicitation_number")
    )
    if not rfqs:
        return JsonResponse({"error": "No queued RFQs for this supplier"}, status=400)

    pers = (request.GET.get("personalization") or "").strip()
    _subject, body_plain = compose_grouped_rfq_email_message(
        supplier, rfqs, request.user, personalization_text=pers
    )
    safe = html.escape(body_plain)
    preview_html = f'<div class="rfq-preview-body" style="white-space:pre-wrap;font-family:system-ui,sans-serif;font-size:0.9rem;">{safe}</div>'
    return JsonResponse({"preview_html": preview_html})


@login_required
@require_POST
def rfq_queue_fetch_pdfs(request):
    """
    POST: supplier_ids[] (list of int).
    Fetch PDFs for QUEUED rfqs of those suppliers where pdf_blob is missing.
    Return JSON { fetched: N, failed: M }.
    """
    from sales.services.dibbs_pdf import fetch_pdfs_for_sols, persist_pdf_procurement_extract

    raw_ids = request.POST.getlist("supplier_ids[]") or request.POST.getlist("supplier_ids")
    try:
        supplier_ids = [int(x) for x in raw_ids if str(x).isdigit()]
    except (ValueError, TypeError):
        return JsonResponse({"fetched": 0, "failed": 0})

    if not supplier_ids:
        return JsonResponse({"fetched": 0, "failed": 0})

    queued = SupplierRFQ.objects.filter(
        status__in=("QUEUED", "READY_TO_SEND"),
        supplier_id__in=supplier_ids,
    ).select_related("line__solicitation")
    sol_numbers = []
    for rfq in queued:
        sol = rfq.line.solicitation
        if not getattr(sol, "pdf_blob", None) or not sol.pdf_blob:
            sol_numbers.append(sol.solicitation_number)
    sol_numbers = list(dict.fromkeys(sol_numbers))

    if not sol_numbers:
        return JsonResponse({"fetched": 0, "failed": 0})

    results = fetch_pdfs_for_sols(sol_numbers)
    now = timezone.now()
    fetched = 0
    failed = 0
    for sol_number, body in results.items():
        if body and len(body) > 0:
            key = (sol_number or "").strip().upper()
            Solicitation.objects.filter(solicitation_number=sol_number).update(
                pdf_blob=body,
                pdf_fetched_at=now,
                pdf_fetch_status="DONE",
            )
            persist_pdf_procurement_extract(key, body)
            fetched += 1
        else:
            failed += 1
    return JsonResponse({"fetched": fetched, "failed": failed})


@login_required
@require_POST
def rfq_queue_send(request):
    """
    POST: supplier_ids[] OR send_all=1.
    Approves queued RFQs for async send: sets ``QUEUED`` rows to ``READY_TO_SEND``
    (same staging behavior as the main queue form). Does not call Graph or build
    grouped email payloads here.
    """
    send_all = request.POST.get("send_all") == "1" or "send_all" in request.POST.getlist("send_all")
    raw_ids = request.POST.getlist("supplier_ids[]") or request.POST.getlist("supplier_ids")
    try:
        supplier_ids = [int(x) for x in raw_ids if str(x).isdigit()]
    except (ValueError, TypeError):
        supplier_ids = []

    no_quote_cages = get_no_quote_cage_set()

    if send_all:
        sid_list = list(
            SupplierRFQ.objects.filter(status__in=("QUEUED", "READY_TO_SEND"))
            .values_list("supplier_id", flat=True)
            .distinct()
        )
        cage_by_sid = dict(
            Supplier.objects.filter(pk__in=sid_list).values_list("id", "cage_code")
        )
        supplier_ids = [
            sid for sid in sid_list
            if normalize_cage_code(cage_by_sid.get(sid)) not in no_quote_cages
        ]
    else:
        if not supplier_ids:
            messages.warning(request, "No suppliers selected for send.")
            return redirect("sales:rfq_queue")
        cage_by_sid = dict(
            Supplier.objects.filter(pk__in=supplier_ids).values_list("id", "cage_code")
        )
        supplier_ids = [
            sid for sid in supplier_ids
            if normalize_cage_code(cage_by_sid.get(sid)) not in no_quote_cages
        ]

    if not supplier_ids:
        messages.info(
            request,
            "No suppliers to send (queue empty, none selected, or all on the No Quote list).",
        )
        return redirect("sales:rfq_queue")

    approved_rfq_total = 0
    for sid in supplier_ids:
        rfqs = list(
            SupplierRFQ.objects.filter(
                status__in=("QUEUED", "READY_TO_SEND"),
                supplier_id=sid,
            )
            .select_related("supplier", "line__solicitation")
            .order_by("line__solicitation__solicitation_number")
        )
        if not rfqs or not any(r.status == "QUEUED" for r in rfqs):
            continue
        supplier = rfqs[0].supplier
        name = (supplier.name or supplier.cage_code or f"Supplier {sid}").strip()

        send_email = _resolve_send_email(supplier)
        if not send_email:
            messages.warning(
                request,
                f"Skipped {name}: no email address on file.",
            )
            continue

        for r in rfqs:
            if r.status == "QUEUED":
                r.status = "READY_TO_SEND"
                r.save(update_fields=["status"])
                approved_rfq_total += 1

    if approved_rfq_total:
        messages.success(
            request,
            f"{approved_rfq_total} RFQ(s) approved for send — emails will go out within 15 minutes.",
        )
    else:
        messages.info(request, "No queued RFQs were approved for send.")

    return redirect("sales:rfq_queue")


@login_required
@require_POST
def rfq_queue_mark_sent(request):
    """
    POST: parallel ``rfq_ids`` and ``email_sent_to`` lists (one pair per RFQ).
    Confirms manual mailto sends: set SENT, log contact, advance solicitations.
    """
    rfq_ids = request.POST.getlist("rfq_ids")
    emails = request.POST.getlist("email_sent_to")
    if len(rfq_ids) != len(emails) or not rfq_ids:
        messages.error(request, "Invalid confirmation data.")
        return redirect("sales:rfq_queue")

    now = timezone.now()
    confirmed = 0
    with transaction.atomic():
        for rid_str, em in zip(rfq_ids, emails):
            if not str(rid_str).isdigit():
                continue
            rfq = (
                SupplierRFQ.objects.select_related("supplier", "line__solicitation")
                .filter(pk=int(rid_str), status="QUEUED")
                .first()
            )
            if not rfq:
                continue
            supplier = rfq.supplier
            sol = rfq.line.solicitation
            to_addr = (em or "").strip()
            rfq.status = "SENT"
            rfq.sent_at = now
            rfq.email_sent_to = to_addr or None
            rfq.sent_by = request.user
            rfq.save(update_fields=["status", "sent_at", "email_sent_to", "sent_by"])

            SupplierContactLog.objects.create(
                rfq=rfq,
                supplier=supplier,
                solicitation=sol,
                method="EMAIL_OUT",
                direction="OUT",
                summary="RFQ sent via mailto (manual)",
                logged_by=request.user,
            )

            if sol.status in ("New", "Active", "Matching", "RFQ_PENDING"):
                sol.status = "RFQ_SENT"
                sol.save(update_fields=["status"])
            confirmed += 1

    if confirmed:
        messages.success(request, f"Marked {confirmed} RFQ(s) as sent.")
    else:
        messages.warning(request, "No queued RFQs were updated (already sent or invalid IDs).")

    return redirect("sales:rfq_queue")


# ──────────────────────────────────────────────
# Graph Inbox (Microsoft Graph — GRAPH_MAIL_SENDER mailbox)
# ──────────────────────────────────────────────


def _build_rfq_inbox_message_context():
    """Build inbox list context from Graph + local RFQ link metadata."""
    messages_raw, error = fetch_inbox_messages()

    graph_ids = [m.graph_id for m in messages_raw]
    stored = (
        InboxMessage.objects.prefetch_related(
            'rfq_links__rfq__line__solicitation',
        )
        .filter(graph_message_id__in=graph_ids)
        if graph_ids
        else InboxMessage.objects.none()
    )
    stored_map = {s.graph_message_id: s for s in stored}

    for msg in messages_raw:
        db_record = stored_map.get(msg.graph_id)
        if db_record:
            msg.is_linked = True
            msg.linked_rfq_ids = list(
                db_record.rfq_links.values_list('rfq_id', flat=True)
            )
            sols = list(
                db_record.rfq_links.select_related(
                    'rfq__supplier', 'rfq__line__solicitation',
                )
            )
            sol_nums = []
            msg.linked_rfqs_display = []
            for link in sols:
                rfq = link.rfq
                sol = rfq.line.solicitation if rfq.line_id else None
                sn = sol.solicitation_number if sol else ''
                if sn:
                    sol_nums.append(sn)
                msg.linked_rfqs_display.append({
                    'rfq_id': rfq.pk,
                    'sol_number': sn,
                    'supplier_name': (rfq.supplier.name if rfq.supplier_id else '')
                    or (rfq.supplier.cage_code if rfq.supplier_id else '')
                    or '—',
                })
            msg.linked_sol_numbers = sorted(set(sol_nums))
            msg.linked_rfqs_json = json.dumps(msg.linked_rfqs_display)
        else:
            msg.linked_rfqs_json = '[]'

    return {
        'inbox_messages': messages_raw,
        'inbox_error': error,
    }


@login_required
def rfq_inbox(request):
    """
    Renders the Inbox tab of the RFQ Center (full page).

    Fetches the 50 most recent messages from the GRAPH_MAIL_SENDER mailbox via Graph.
    Merges live Graph results with locally stored InboxMessage rows for link badges.
    """
    context = _build_rfq_inbox_message_context()
    context.update({
        'active_tab': 'inbox',
        'section': 'rfq',
    })
    return render(request, 'sales/rfq/inbox.html', context)


@login_required
@require_GET
def rfq_inbox_refresh(request):
    """
    AJAX endpoint: returns only the inbox list HTML fragment.
    """
    context = _build_rfq_inbox_message_context()
    return render(request, 'sales/rfq/partials/inbox_list.html', context)


@login_required
def rfq_inbox_message_body(request, graph_message_id):
    """
    AJAX endpoint. Fetches full HTML body for one Graph message AND handles
    claim logic in a single round trip.

    Claim behavior:
    - If message is already linked (has rfq_links): no claim logic, return body freely.
    - If message has an active claim by another user (non-expired): do not overwrite
      the claim. Return body plus claim warning data so JS can show the warning.
    - If message has no claim, or claim is expired, or claim belongs to request.user:
      write/refresh the claim for request.user, return body with claim_status='owned'.

    Response JSON:
    {
        "html": "<...>",
        "error": null,
        "claim_status": "owned" | "claimed_by_other" | "linked" | "new",
        "claimed_by_name": "Sarah Smith",   // only when claim_status == "claimed_by_other"
        "claimed_at_display": "10:42 AM",   // only when claim_status == "claimed_by_other"
        "graph_message_id": "..."           // echoed back for JS convenience
    }
    """
    body_html, error = fetch_message_body(graph_message_id)

    response_data = {
        'html': body_html,
        'error': error,
        'graph_message_id': graph_message_id,
        'claim_status': 'new',
        'claimed_by_name': '',
        'claimed_at_display': '',
    }

    try:
        inbox_msg = InboxMessage.objects.prefetch_related('rfq_links').get(
            graph_message_id=graph_message_id
        )
    except InboxMessage.DoesNotExist:
        inbox_msg = None

    if inbox_msg and inbox_msg.rfq_links.exists():
        response_data['claim_status'] = 'linked'
        return JsonResponse(response_data)

    if inbox_msg and inbox_msg.is_claimed_by_other(request.user):
        response_data['claim_status'] = 'claimed_by_other'
        claimer = inbox_msg.claimed_by
        response_data['claimed_by_name'] = (
            (claimer.get_full_name() or claimer.username) if claimer else 'Another user'
        )
        if inbox_msg.claimed_at:
            local_time = timezone.localtime(inbox_msg.claimed_at)
            # Windows-safe hour format (no %-I support)
            response_data['claimed_at_display'] = local_time.strftime('%I:%M %p').lstrip('0')
        return JsonResponse(response_data)

    if not inbox_msg:
        sender_email = request.GET.get('sender_email', '')
        sender_name = request.GET.get('sender_name', '')
        subject = request.GET.get('subject', '')
        received_at_str = request.GET.get('received_at', '')

        from django.utils.dateparse import parse_datetime
        received_at = parse_datetime(received_at_str) if received_at_str else None
        if received_at is None:
            received_at = timezone.now()
        if received_at.tzinfo is None:
            received_at = timezone.make_aware(received_at)

        now = timezone.now()
        inbox_msg = InboxMessage.objects.create(
            graph_message_id=graph_message_id,
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            received_at=received_at,
            body_html='',
            is_read=False,
            claimed_by=request.user,
            claimed_at=now,
            claim_expires_at=now + timedelta(minutes=20),
        )
    else:
        inbox_msg.claim_for(request.user)

    response_data['claim_status'] = 'owned'
    return JsonResponse(response_data)


@login_required
@require_POST
def rfq_inbox_override_claim(request, graph_message_id):
    """
    POST endpoint. Overrides an existing claim on a message, transferring it
    to request.user. Used only when a rep explicitly chooses to override another
    user's active claim via the confirmation step in the UI.

    Returns JSON { success: true, claim_status: 'owned' }
    """
    try:
        inbox_msg = InboxMessage.objects.get(graph_message_id=graph_message_id)
    except InboxMessage.DoesNotExist:
        return JsonResponse({'success': True, 'claim_status': 'owned'})

    inbox_msg.claim_for(request.user)
    return JsonResponse({'success': True, 'claim_status': 'owned'})


@login_required
@require_POST
def rfq_inbox_link(request, graph_message_id):
    """
    POST: link one inbox message to one or more SupplierRFQ rows (persist InboxMessage + links).
    """
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone as tz

    if request.content_type and 'application/json' in request.content_type:
        try:
            payload = json.loads(request.body)
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    else:
        payload = request.POST

    rfq_ids_raw = payload.get('rfq_ids', '')
    try:
        rfq_id_list = [int(x.strip()) for x in rfq_ids_raw.split(',') if x.strip()]
    except ValueError:
        return JsonResponse(
            {'success': False, 'error': 'rfq_ids must be comma-separated integers'},
            status=400,
        )

    if not rfq_id_list:
        return JsonResponse({'success': False, 'error': 'No RFQ IDs provided'}, status=400)

    sender_email = (payload.get('sender_email') or '').strip()
    sender_name = (payload.get('sender_name') or '').strip()
    subject = (payload.get('subject') or '').strip()
    received_at_str = (payload.get('received_at') or '').strip()
    notes = (payload.get('notes') or '').strip()

    if not sender_email:
        return JsonResponse(
            {'success': False, 'error': 'sender_email is required'},
            status=400,
        )

    received_at = parse_datetime(received_at_str) if received_at_str else None
    if received_at is None:
        received_at = tz.now()
    if received_at.tzinfo is None:
        received_at = tz.make_aware(received_at)

    body_html, _ = fetch_message_body(graph_message_id)

    inbox_msg, _ = InboxMessage.objects.get_or_create(
        graph_message_id=graph_message_id,
        defaults={
            'sender_email': sender_email,
            'sender_name': sender_name,
            'subject': subject,
            'received_at': received_at,
            'body_html': body_html,
            'is_read': True,
        },
    )

    rfqs = SupplierRFQ.objects.select_related(
        'supplier', 'line__solicitation',
    ).filter(pk__in=rfq_id_list)
    for rfq in rfqs:
        InboxMessageRFQLink.objects.get_or_create(
            message=inbox_msg,
            rfq=rfq,
            defaults={
                'linked_by': request.user,
                'notes': notes,
            },
        )

    mark_message_read(graph_message_id)

    # Full list for UI (includes prior links on this message)
    all_links = inbox_msg.rfq_links.select_related(
        'rfq__supplier', 'rfq__line__solicitation',
    )
    linked_rfqs_meta = []
    for link in all_links:
        rfq = link.rfq
        sol = rfq.line.solicitation if rfq.line_id else None
        linked_rfqs_meta.append({
            'rfq_id': rfq.pk,
            'sol_number': sol.solicitation_number if sol else '',
            'supplier_name': (rfq.supplier.name if rfq.supplier_id else '')
            or (rfq.supplier.cage_code if rfq.supplier_id else '')
            or '—',
        })
    sols_ordered = sorted({x['sol_number'] for x in linked_rfqs_meta if x.get('sol_number')})
    return JsonResponse({
        'success': True,
        'linked_sol_numbers': sols_ordered,
        'linked_rfqs': linked_rfqs_meta,
    })


@login_required
def rfq_inbox_rfq_search(request):
    """
    AJAX GET: search SENT SupplierRFQs for the link modal.
    """
    q = request.GET.get('q', '').strip()
    email = request.GET.get('email', '').strip()

    qs = SupplierRFQ.objects.select_related(
        'line__solicitation', 'supplier',
    ).filter(status='SENT')

    if email:
        qs = qs.filter(
            Q(supplier__rfq_email__iexact=email)
            | Q(supplier__business_email__iexact=email)
            | Q(supplier__primary_email__iexact=email)
        )

    if q:
        qs = qs.filter(
            Q(line__solicitation__solicitation_number__icontains=q)
            | Q(supplier__name__icontains=q)
        )

    qs = qs.order_by('-sent_at', '-id')[:30]

    results = []
    for rfq in qs:
        sol = rfq.line.solicitation if rfq.line_id else None
        sup = rfq.supplier
        results.append({
            'rfq_id': rfq.pk,
            'sol_number': sol.solicitation_number if sol else '',
            'supplier_name': sup.name if sup else '',
            'supplier_email': (
                (getattr(sup, 'rfq_email', None) or '')
                or (getattr(sup, 'business_email', None) or '')
                or (getattr(sup, 'primary_email', None) or '')
            ),
            'status': rfq.status,
            'sent_at': rfq.sent_at.isoformat() if rfq.sent_at else '',
        })

    return JsonResponse(results, safe=False)
