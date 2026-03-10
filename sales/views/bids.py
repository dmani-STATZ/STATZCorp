"""
Bid Center views: ready list, bid builder, export queue, export download.
"""
from datetime import date
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse

from sales.models import (
    Solicitation,
    SolicitationLine,
    SupplierQuote,
    GovernmentBid,
    CompanyCAGE,
    ApprovedSource,
)
from sales.services.bq_export import generate_bq_file, BQExportError, validate_bid_for_export


def _resolve_selected_quote(quotes):
    """Defensive: selected is_selected_for_bid, or cheapest."""
    selected = quotes.filter(is_selected_for_bid=True).order_by("-quote_date").first()
    if selected:
        return selected
    return quotes.order_by("unit_price").first()


@login_required
def bids_ready(request):
    """
    Lines that have at least one quote but no completed bid (or bid in DRAFT).
    """
    lines_with_quotes = (
        SolicitationLine.objects.filter(
            supplier_quotes__isnull=False,
            solicitation__status__in=["QUOTING", "BID_READY"],
        )
        .exclude(bid__bid_status="SUBMITTED")
        .distinct()
        .select_related("solicitation")
        .prefetch_related("supplier_quotes__supplier", "bid")
    )

    cage = CompanyCAGE.objects.filter(is_default=True, is_active=True).first()
    default_markup_pct = float(cage.default_markup_pct) if cage else 3.50

    bid_lines = []
    for line in lines_with_quotes:
        quotes = list(line.supplier_quotes.all())
        if not quotes:
            continue
        best_quote = min(quotes, key=lambda q: q.unit_price)
        suggested_bid = float(best_quote.unit_price) * (1 + default_markup_pct / 100)
        existing_bid = getattr(line, "bid", None)
        bid_lines.append({
            "line": line,
            "solicitation": line.solicitation,
            "best_quote": best_quote,
            "suggested_bid": suggested_bid,
            "quote_count": len(quotes),
            "existing_bid": existing_bid,
        })

    return render(request, "sales/bids/ready.html", {
        "bid_lines": bid_lines,
        "total_count": len(bid_lines),
        "default_markup_pct": default_markup_pct,
    })


@login_required
@require_http_methods(["GET", "POST"])
def bid_builder(request, sol_number):
    """
    Assemble a GovernmentBid for the solicitation. One line per sol (first or ?line= pk).
    POST: save_draft or mark_ready.
    """
    solicitation = get_object_or_404(Solicitation, solicitation_number=sol_number)
    line_id = request.GET.get("line") or request.POST.get("line")
    if line_id:
        line = get_object_or_404(SolicitationLine, pk=line_id, solicitation=solicitation)
    else:
        line = solicitation.lines.order_by("line_number", "id").first()
        if not line:
            messages.warning(request, "No lines on this solicitation.")
            return redirect("sales:bids_ready")

    quotes = SupplierQuote.objects.filter(line=line).select_related("supplier").order_by("unit_price")
    quotes_list = list(quotes)
    if not quotes_list:
        messages.warning(request, "No quotes for this line. Enter quotes from RFQ Center.")
        return redirect("sales:bids_ready")

    selected_quote = _resolve_selected_quote(quotes)
    if not selected_quote:
        selected_quote = quotes_list[0]

    company_cages = CompanyCAGE.objects.filter(is_active=True).order_by("-is_default")
    default_cage = company_cages.filter(is_default=True).first() or company_cages.first()
    default_markup_pct = float(default_cage.default_markup_pct) if default_cage else 3.50
    suggested_bid_price = float(selected_quote.unit_price) * (1 + default_markup_pct / 100)
    suggested_delivery_days = selected_quote.lead_time_days

    nsn_normalized = (line.nsn or "").replace("-", "").strip()
    approved_sources = list(ApprovedSource.objects.filter(nsn=nsn_normalized))
    existing_bid = getattr(line, "bid", None)

    if request.method == "POST":
        action = request.POST.get("action", "save_draft")
        # Validate and build bid data from POST
        unit_price = request.POST.get("unit_price")
        delivery_days = request.POST.get("delivery_days")
        quoter_cage = (request.POST.get("quoter_cage") or "").strip()[:5]
        quote_for_cage = (request.POST.get("quote_for_cage") or quoter_cage).strip()[:5]
        bid_type_code = (request.POST.get("bid_type_code") or "BI").strip()[:2]
        fob_point = (request.POST.get("fob_point") or "D").strip()[:1]
        payment_terms = (request.POST.get("payment_terms") or "").strip()[:2]
        manufacturer_dealer = (request.POST.get("manufacturer_dealer") or "DD").strip()[:2]
        mfg_source_cage = (request.POST.get("mfg_source_cage") or "").strip()[:5]
        material_requirements = (request.POST.get("material_requirements") or "0").strip()[:1]
        hazardous_material = (request.POST.get("hazardous_material") or "N").strip()[:1]
        bid_remarks = (request.POST.get("bid_remarks") or "").strip()[:255]
        part_number_offered_code = (request.POST.get("part_number_offered_code") or "").strip()[:1] or None
        part_number_offered_cage = (request.POST.get("part_number_offered_cage") or "").strip()[:5] or None
        part_number_offered = (request.POST.get("part_number_offered") or "").strip()[:40] or None

        try:
            up = Decimal(str(unit_price).strip()) if unit_price else None
            dd = int(delivery_days) if delivery_days else None
        except (ValueError, TypeError):
            up = None
            dd = None

        if not up or up <= 0:
            messages.error(request, "Unit price is required and must be > 0.")
        elif not dd or dd <= 0:
            messages.error(request, "Delivery days are required and must be > 0.")
        elif not quoter_cage or len(quoter_cage) != 5:
            messages.error(request, "Quoter CAGE must be 5 characters.")
        else:
            supplier_cost = float(selected_quote.unit_price)
            margin_pct = (float(up) - supplier_cost) / float(up) * 100 if up else None

            defaults = {
                "solicitation": solicitation,
                "quoter_cage": quoter_cage,
                "quote_for_cage": quote_for_cage or quoter_cage,
                "bid_type_code": bid_type_code,
                "unit_price": up,
                "delivery_days": dd,
                "fob_point": fob_point,
                "payment_terms": payment_terms or (default_cage.default_payment_terms if default_cage else "1"),
                "manufacturer_dealer": manufacturer_dealer,
                "mfg_source_cage": mfg_source_cage if manufacturer_dealer in ("DD", "QD") else None,
                "material_requirements": material_requirements,
                "hazardous_material": hazardous_material,
                "bid_remarks": bid_remarks if bid_type_code in ("BW", "AB") else "",
                "part_number_offered_code": part_number_offered_code,
                "part_number_offered_cage": part_number_offered_cage,
                "part_number_offered": part_number_offered,
                "selected_quote": selected_quote,
                "margin_pct": margin_pct,
                "bid_status": "DRAFT",
            }
            bid, created = GovernmentBid.objects.update_or_create(
                line=line,
                defaults=defaults,
            )
            if action == "mark_ready":
                solicitation.status = "BID_READY"
                solicitation.save(update_fields=["status"])
                messages.success(request, "Bid marked ready to export.")
            else:
                messages.success(request, "Draft saved.")
            return redirect("sales:bids_ready")

    # GET: prefill from existing_bid or defaults
    if existing_bid:
        initial_price = existing_bid.unit_price
        initial_delivery = existing_bid.delivery_days
        initial_cage = existing_bid.quoter_cage
        initial_quote_cage = existing_bid.quote_for_cage
        initial_bid_type = existing_bid.bid_type_code
        initial_fob = existing_bid.fob_point
        initial_payment = existing_bid.payment_terms
        initial_md = existing_bid.manufacturer_dealer
        initial_mfg_cage = existing_bid.mfg_source_cage
        initial_material = existing_bid.material_requirements
        initial_hazmat = existing_bid.hazardous_material
        initial_remarks = existing_bid.bid_remarks
        initial_pn_code = existing_bid.part_number_offered_code
        initial_pn_cage = existing_bid.part_number_offered_cage
        initial_pn = existing_bid.part_number_offered
    else:
        initial_price = suggested_bid_price
        initial_delivery = suggested_delivery_days
        initial_cage = default_cage.cage_code if default_cage else ""
        initial_quote_cage = initial_cage
        initial_bid_type = "BI"
        initial_fob = default_cage.default_fob_point if default_cage else "D"
        initial_payment = default_cage.default_payment_terms if default_cage else "1"
        initial_md = "DD"
        initial_mfg_cage = (selected_quote.supplier.cage_code or "")[:5] if selected_quote.supplier else ""
        initial_material = "0"
        initial_hazmat = "N"
        initial_remarks = ""
        first_as = approved_sources[0] if approved_sources else None
        initial_pn_code = ""
        initial_pn_cage = first_as.approved_cage if first_as else ""
        initial_pn = first_as.part_number[:40] if first_as and first_as.part_number else ""

    return render(request, "sales/bids/builder.html", {
        "solicitation": solicitation,
        "line": line,
        "approved_sources": approved_sources,
        "quotes": quotes_list,
        "selected_quote": selected_quote,
        "existing_bid": existing_bid,
        "company_cages": company_cages,
        "default_cage": default_cage,
        "suggested_bid_price": suggested_bid_price,
        "suggested_delivery_days": suggested_delivery_days,
        "default_markup_pct": default_markup_pct,
        "initial_price": initial_price,
        "initial_delivery": initial_delivery,
        "initial_cage": initial_cage,
        "initial_quote_cage": initial_quote_cage,
        "initial_bid_type": initial_bid_type,
        "initial_fob": initial_fob,
        "initial_payment": initial_payment,
        "initial_md": initial_md,
        "initial_mfg_cage": initial_mfg_cage,
        "initial_material": initial_material,
        "initial_hazmat": initial_hazmat,
        "initial_remarks": initial_remarks,
        "initial_pn_code": initial_pn_code,
        "initial_pn_cage": initial_pn_cage,
        "initial_pn": initial_pn,
        "show_part_number_section": (line.item_description_indicator or "") in "PBN",
    })


@login_required
@require_POST
def bid_select_quote(request):
    """Set is_selected_for_bid=True for quote_id; clear others for same line. Redirect to bid_builder."""
    quote_id = request.POST.get("quote_id")
    if not quote_id:
        messages.warning(request, "No quote selected.")
        return redirect("sales:bids_ready")
    quote = get_object_or_404(
        SupplierQuote.objects.select_related("line__solicitation"),
        pk=quote_id,
    )
    SupplierQuote.objects.filter(line=quote.line).update(is_selected_for_bid=False)
    quote.is_selected_for_bid = True
    quote.save(update_fields=["is_selected_for_bid"])
    messages.success(request, "Quote selected for bid.")
    return redirect("sales:bid_builder", sol_number=quote.line.solicitation.solicitation_number)


@login_required
def bids_export_queue(request):
    """List GovernmentBid in DRAFT where solicitation status is BID_READY."""
    export_bids = (
        GovernmentBid.objects.filter(
            bid_status="DRAFT",
            solicitation__status="BID_READY",
        )
        .select_related("solicitation", "line", "selected_quote", "selected_quote__supplier")
    )
    total_count = export_bids.count()
    return render(request, "sales/bids/export_queue.html", {
        "export_bids": export_bids,
        "total_count": total_count,
    })


@login_required
@require_POST
def bids_export_download(request):
    """POST: bid_ids[]. Generate BQ file, return download. On validation error re-render export_queue with errors."""
    bid_ids = request.POST.getlist("bid_ids[]") or request.POST.getlist("bid_ids")
    bid_ids = [int(x) for x in bid_ids if str(x).isdigit()]
    if not bid_ids:
        messages.warning(request, "No bids selected.")
        return redirect("sales:bids_export_queue")

    try:
        content = generate_bq_file(bid_ids)
    except BQExportError as e:
        export_bids = (
            GovernmentBid.objects.filter(bid_status="DRAFT", solicitation__status="BID_READY")
            .select_related("solicitation", "line", "selected_quote")
        )
        return render(request, "sales/bids/export_queue.html", {
            "export_bids": export_bids,
            "total_count": export_bids.count(),
            "export_errors": e.errors,
        })

    from django.utils import timezone
    filename = f"bq{date.today().strftime('%y%m%d')}.txt"
    for bid in GovernmentBid.objects.filter(pk__in=bid_ids):
        bid.bid_status = "SUBMITTED"
        bid.submitted_at = timezone.now()
        bid.exported_bq_file = filename
        bid.save(update_fields=["bid_status", "submitted_at", "exported_bq_file"])
        bid.solicitation.status = "BID_SUBMITTED"
        bid.solicitation.save(update_fields=["status"])

    response = HttpResponse(content, content_type="text/plain")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
