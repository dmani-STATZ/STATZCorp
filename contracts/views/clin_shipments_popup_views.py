"""Standalone CLIN shipments popup. GET only."""

from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from STATZWeb.decorators import conditional_login_required

from ..models import Clin, ClinShipment
from ..services.pod_status import compute_pod_status
from ..services.shipment_labels import label_shipments


def _open_target(request, shipments):
    """Which modal to open from the query string.

    ``add=1`` wins. ``edit`` must be an integer id of a shipment on this
    CLIN. Anything else is ignored.
    """
    if request.GET.get("add") == "1":
        return "add", ""
    raw = request.GET.get("edit")
    if raw is None or str(raw).strip() == "":
        return "", ""
    try:
        edit_id = int(str(raw).strip())
    except (TypeError, ValueError):
        return "", ""
    if any(shipment.id == edit_id for shipment in shipments):
        return "edit", edit_id
    return "", ""


def _shipped_header(clin):
    """Shipped number, color class, and the complete check.

    Null ship_qty is treated as 0. A null order_qty leaves the class empty
    so the template can show the shipped number alone.
    """
    shipped_qty = 0 if clin.ship_qty is None else clin.ship_qty
    order_qty = clin.order_qty
    is_shipping_complete = bool(
        clin.ship_qty
        and order_qty
        and clin.ship_qty > 0
        and order_qty > 0
        and clin.ship_qty == order_qty
    )
    shipped_class = ""
    if order_qty is not None:
        if shipped_qty < order_qty:
            shipped_class = "text-danger"
        elif shipped_qty > order_qty:
            shipped_class = "text-warning"
        elif is_shipping_complete:
            shipped_class = "text-success"
    return shipped_qty, shipped_class, is_shipping_complete


@conditional_login_required
@require_http_methods(["GET"])
def clin_shipments_popup(request, clin_id):
    """Render the shipments page for one CLIN."""
    company = getattr(request, "active_company", None)
    if not company:
        return HttpResponseForbidden("No active company")

    clin = get_object_or_404(
        Clin.objects.filter(contract__company=company).select_related("contract"),
        id=clin_id,
    )
    # Meta.ordering stays ship-date desc. Labels and row order are entry order.
    shipments = label_shipments(list(clin.shipments.all()))
    shipped_qty, shipped_class, is_shipping_complete = _shipped_header(clin)
    comments_field = ClinShipment._meta.get_field("comments")
    name_field = ClinShipment._meta.get_field("name")
    open_mode, open_shipment_id = _open_target(request, shipments)
    return render(
        request,
        "contracts/clin_shipments_popup.html",
        {
            "clin": clin,
            "shipments": shipments,
            "pod_status": compute_pod_status(clin, shipments=shipments),
            "can_complete": bool(shipments) and all(
                shipment.pod_date is not None for shipment in shipments
            ),
            "is_shipping_complete": is_shipping_complete,
            "shipped_qty": shipped_qty,
            "shipped_class": shipped_class,
            "open_mode": open_mode,
            "open_shipment_id": open_shipment_id,
            "comments_max_length": comments_field.max_length,
            "name_max_length": name_field.max_length,
        },
    )
