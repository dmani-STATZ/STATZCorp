"""
RFQ dispatch and quote entry views. Section 10.5, 10.8.
"""
import logging
import urllib.parse
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.contrib import messages
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone
from django.http import JsonResponse

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
)
from sales.models.inbox import InboxEmail
from sales.services.email import (
    send_rfq_email,
    send_followup_email,
    resolve_supplier_email,
    resolve_supplier_email_for_send,
    build_grouped_rfq_email,
)
from sales.services.imap_fetch import fetch_inbox_emails, _apply_match
from sales.services.suppliers import create_supplier_from_sam, get_or_create_stub_supplier

logger = logging.getLogger(__name__)


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
        m.rfq_sent = False
        m.rfq_status_display = ""
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
    status_order = ["New", "Matching", "RFQ_PENDING", "RFQ_SENT", "QUOTING", "BID_READY", "BID_SUBMITTED"]
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

    unread_count = InboxEmail.objects.filter(is_read=False).count()
    queued_count = SupplierRFQ.objects.filter(status="QUEUED").count()

    return render(request, "sales/rfq/center.html", {
        "rfq_groups_display": rfq_groups_display,
        "selected_rfq_id": selected_rfq_id or 0,
        "default_markup_pct": default_markup_pct,
        "today": today,
        "unread_count": unread_count,
        "queued_count": queued_count,
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

    if SupplierRFQ.objects.filter(line=line, supplier=supplier, status="QUEUED").exists():
        return JsonResponse({"status": "already_queued"})

    rfq = SupplierRFQ.objects.create(
        line=line,
        supplier=supplier,
        status="QUEUED",
        sent_by=request.user,
    )

    if solicitation.status in ("New", "Matching"):
        solicitation.status = "RFQ_PENDING"
        solicitation.save(update_fields=["status"])

    return JsonResponse({"status": "queued", "rfq_id": rfq.pk})


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
                line=line, supplier=supplier, status="QUEUED"
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

            if solicitation.status in ("New", "Matching"):
                solicitation.status = "RFQ_PENDING"
                solicitation.save(update_fields=["status"])

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


@login_required
@require_GET
def rfq_queue_view(request):
    """
    GET: render Queue tab content — all QUEUED RFQs grouped by supplier.
    Context: grouped_queue, total_queued.
    """
    from collections import OrderedDict
    from suppliers.models import Supplier

    qs = (
        SupplierRFQ.objects.filter(status="QUEUED")
        .select_related("supplier", "line", "line__solicitation")
        .prefetch_related("supplier__contacts")
        .order_by("supplier__name", "line__solicitation__solicitation_number")
    )
    rfq_list = list(qs)

    groups = OrderedDict()
    for rfq in rfq_list:
        sid = rfq.supplier_id
        if sid not in groups:
            send_email = _resolve_send_email(rfq.supplier)
            groups[sid] = {
                "supplier": rfq.supplier,
                "rfqs": [],
                "has_missing_pdfs": False,
                "send_email": send_email,
            }
        groups[sid]["rfqs"].append(rfq)
        sol = rfq.line.solicitation
        if not getattr(sol, "pdf_blob", None) or not sol.pdf_blob:
            groups[sid]["has_missing_pdfs"] = True

    grouped_queue = list(groups.values())
    total_queued = len(rfq_list)
    today = timezone.now().date()

    return render(request, "sales/rfq/queue.html", {
        "grouped_queue": grouped_queue,
        "total_queued": total_queued,
        "today": today,
    })


@login_required
@require_POST
def rfq_queue_fetch_pdfs(request):
    """
    POST: supplier_ids[] (list of int).
    Fetch PDFs for QUEUED rfqs of those suppliers where pdf_blob is missing.
    Return JSON { fetched: N, failed: M }.
    """
    from sales.services.dibbs_pdf import fetch_pdfs_for_sols

    raw_ids = request.POST.getlist("supplier_ids[]") or request.POST.getlist("supplier_ids")
    try:
        supplier_ids = [int(x) for x in raw_ids if str(x).isdigit()]
    except (ValueError, TypeError):
        return JsonResponse({"fetched": 0, "failed": 0})

    if not supplier_ids:
        return JsonResponse({"fetched": 0, "failed": 0})

    queued = (
        SupplierRFQ.objects.filter(status="QUEUED", supplier_id__in=supplier_ids)
        .select_related("line__solicitation")
    )
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
            Solicitation.objects.filter(solicitation_number=sol_number).update(
                pdf_blob=body, pdf_fetched_at=now
            )
            fetched += 1
        else:
            failed += 1
    return JsonResponse({"fetched": fetched, "failed": failed})


@login_required
@require_POST
def rfq_queue_send(request):
    """
    POST: supplier_ids[] OR send_all=1.
    For each supplier: resolve email, build_grouped_rfq_email, send; on success
    mark rfqs SENT, contact log, advance solicitation to RFQ_SENT.
    Return JSON { sent_to: [names], failed: [{ supplier, reason }] }.
    """
    from django.core.mail import EmailMessage

    send_all = request.POST.get("send_all") == "1" or "send_all" in request.POST.getlist("send_all")
    raw_ids = request.POST.getlist("supplier_ids[]") or request.POST.getlist("supplier_ids")
    try:
        supplier_ids = [int(x) for x in raw_ids if str(x).isdigit()]
    except (ValueError, TypeError):
        supplier_ids = []

    if send_all:
        supplier_ids = list(
            SupplierRFQ.objects.filter(status="QUEUED")
            .values_list("supplier_id", flat=True)
            .distinct()
        )
    elif not supplier_ids:
        return JsonResponse({"sent_to": [], "failed": []})

    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    from_email = getattr(cage, "smtp_reply_to", None) if cage else None
    if not from_email:
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost"

    sent_to = []
    failed = []
    for sid in supplier_ids:
        rfqs = list(
            SupplierRFQ.objects.filter(status="QUEUED", supplier_id=sid)
            .select_related("supplier", "line__solicitation")
            .order_by("line__solicitation__solicitation_number")
        )
        if not rfqs:
            continue
        supplier = rfqs[0].supplier
        name = (supplier.name or supplier.cage_code or f"Supplier {sid}").strip()

        send_email = _resolve_send_email(supplier)
        if not send_email:
            failed.append({"supplier": name, "reason": "no email"})
            continue

        try:
            payload = build_grouped_rfq_email(supplier, rfqs, request.user)
        except Exception as e:
            failed.append({"supplier": name, "reason": str(e)})
            continue

        try:
            msg = EmailMessage(
                subject=payload["subject"],
                body=payload["body"],
                from_email=from_email,
                to=[send_email],
                reply_to=[payload["reply_to"]] if payload.get("reply_to") else None,
            )
            for att in payload.get("attachments") or []:
                msg.attach(att["filename"], att["content"], att.get("mimetype", "application/pdf"))
            msg.send(fail_silently=False)
        except Exception as e:
            failed.append({"supplier": name, "reason": str(e)})
            continue

        now = timezone.now()
        for rfq in rfqs:
            rfq.status = "SENT"
            rfq.sent_at = now
            rfq.email_sent_to = send_email
            rfq.sent_by = request.user
            rfq.save(update_fields=["status", "sent_at", "email_sent_to", "sent_by"])
            sol = rfq.line.solicitation
            SupplierContactLog.objects.create(
                rfq=rfq,
                supplier=supplier,
                solicitation=sol,
                method="EMAIL_OUT",
                direction="OUT",
                summary=f"RFQ sent to {send_email}",
                logged_by=request.user,
            )
            if sol.status in ("New", "Matching", "RFQ_PENDING"):
                sol.status = "RFQ_SENT"
                sol.save(update_fields=["status"])
        sent_to.append(name)

    return JsonResponse({"sent_to": sent_to, "failed": failed})


# ──────────────────────────────────────────────
# IMAP Inbox views
# ──────────────────────────────────────────────

@login_required
@require_POST
def rfq_inbox_refresh(request):
    """POST: pull new emails from IMAP using the current user's delegated token."""
    result = fetch_inbox_emails(user=request.user)
    if result["errors"] and not result["fetched"]:
        return JsonResponse({"success": False, "error": result["errors"][0]})
    unread_count = InboxEmail.objects.filter(is_read=False).count()
    return JsonResponse({
        "success": True,
        "fetched": result["fetched"],
        "matched": result["matched"],
        "unread_count": unread_count,
    })


@login_required
@require_GET
def rfq_inbox_list(request):
    """GET: return the inbox email list HTML fragment."""
    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    imap_configured = bool(cage and cage.imap_host and cage.imap_user and cage.imap_password)
    emails = InboxEmail.objects.select_related("rfq__supplier", "rfq__line__solicitation").order_by("-received_at")[:100]
    unread_count = InboxEmail.objects.filter(is_read=False).count()
    return render(request, "sales/rfq/partials/inbox_list.html", {
        "emails": emails,
        "imap_configured": imap_configured,
        "unread_count": unread_count,
    })


@login_required
@require_GET
def rfq_inbox_detail(request, email_id):
    """GET: return the inbox email detail HTML fragment for the center panel. Marks email as read."""
    inbox_email = get_object_or_404(InboxEmail.objects.select_related(
        "rfq__supplier", "rfq__line__solicitation", "rfq__line",
    ), pk=email_id)

    if not inbox_email.is_read:
        inbox_email.is_read = True
        inbox_email.save(update_fields=["is_read"])

    # Build list of SENT RFQs for the manual-assign dropdown (unmatched emails only)
    assignable_rfqs = []
    if not inbox_email.is_matched:
        assignable_rfqs = (
            SupplierRFQ.objects
            .filter(status="SENT")
            .select_related("supplier", "line__solicitation")
            .order_by("-sent_at")[:200]
        )

    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    default_markup_pct = float(cage.default_markup_pct) if cage else 0

    return render(request, "sales/rfq/partials/inbox_detail.html", {
        "inbox_email": inbox_email,
        "assignable_rfqs": assignable_rfqs,
        "default_markup_pct": default_markup_pct,
        "rfq_enter_quote_url": reverse("sales:rfq_enter_quote", args=[0]).rstrip("0"),
    })


@login_required
@require_POST
def rfq_inbox_assign(request, email_id):
    """POST: manually link an unmatched inbox email to an RFQ."""
    inbox_email = get_object_or_404(InboxEmail, pk=email_id)
    rfq_id = request.POST.get("rfq_id")
    if not rfq_id:
        return JsonResponse({"success": False, "error": "rfq_id required"})

    rfq = get_object_or_404(SupplierRFQ.objects.select_related("supplier", "line__solicitation"), pk=rfq_id)
    _apply_match(inbox_email, rfq)
    inbox_email.save()
    return JsonResponse({
        "success": True,
        "rfq_id": rfq.pk,
        "supplier_name": rfq.supplier.name or "",
        "sol_number": rfq.line.solicitation.solicitation_number,
    })
