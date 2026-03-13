"""
RFQ dispatch and quote entry views. Section 10.5, 10.8.
"""
import urllib.parse
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
    EmailTemplate,
)
from sales.services.email import send_rfq_email, send_followup_email
from sales.services.suppliers import create_supplier_from_sam, get_or_create_stub_supplier


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
      1. match.supplier.contact.email  (if contact FK exists and contact has email)
      2. match.supplier.primary_email
      3. match.supplier.business_email

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
    to_email = None
    if getattr(supplier, "contact", None) and supplier.contact and getattr(supplier.contact, "email", None) and supplier.contact.email:
        to_email = supplier.contact.email
    elif getattr(supplier, "primary_email", None) and supplier.primary_email:
        to_email = supplier.primary_email
    elif getattr(supplier, "business_email", None) and supplier.business_email:
        to_email = supplier.business_email

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
    to_email = None
    if getattr(supplier, "contact", None) and supplier.contact and getattr(supplier.contact, "email", None) and supplier.contact.email:
        to_email = supplier.contact.email
    elif getattr(supplier, "primary_email", None) and supplier.primary_email:
        to_email = supplier.primary_email
    elif getattr(supplier, "business_email", None) and supplier.business_email:
        to_email = supplier.business_email

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
    to_email = None
    if getattr(supplier, 'contact', None) and supplier.contact and getattr(supplier.contact, 'email', None):
        to_email = supplier.contact.email
    elif getattr(supplier, 'primary_email', None):
        to_email = supplier.primary_email
    elif getattr(supplier, 'business_email', None):
        to_email = supplier.business_email

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
        email = ''
        contact = getattr(s, 'contact', None)
        if contact and getattr(contact, 'email', None):
            email = contact.email
        elif getattr(s, 'primary_email', None):
            email = s.primary_email
        elif getattr(s, 'business_email', None):
            email = s.business_email

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
    if email_override and not (
        (getattr(supplier, 'contact', None) and getattr(supplier.contact, 'email', None))
        or supplier.primary_email
        or supplier.business_email
    ):
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
