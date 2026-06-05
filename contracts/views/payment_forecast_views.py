import json
from django.views import View
from django.shortcuts import render, get_object_or_404
from django.contrib.contenttypes.models import ContentType
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from STATZWeb.decorators import conditional_login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.utils import timezone

from ..models import SpecialPaymentTerms, ClinShipment, ShipmentPaymentPlan
from ..services.payment_forecast import build_forecast


@method_decorator(conditional_login_required, name="dispatch")
class PaymentForecastView(View):
    def get(self, request, *args, **kwargs):
        company = getattr(request, "active_company", None)
        if not company:
            return HttpResponseForbidden("No active company set")

        try:
            days = int(request.GET.get("days", 60))
            if days < 0:
                days = 60
            elif days > 365:
                days = 365
        except (ValueError, TypeError):
            days = 60

        buckets = build_forecast(company, days=days)
        terms = SpecialPaymentTerms.objects.all().order_by("terms")
        clinshipment_content_type_id = ContentType.objects.get_for_model(ClinShipment).id

        context = {
            "buckets": buckets,
            "days": days,
            "today": timezone.localdate(),
            "terms": terms,
            "clinshipment_content_type_id": clinshipment_content_type_id,
        }
        return render(request, "contracts/payment_forecast.html", context)


@conditional_login_required
@require_http_methods(["POST", "PATCH"])
def upsert_payment_plan(request, shipment_id):
    company = getattr(request, "active_company", None)
    if not company:
        return JsonResponse({"error": "No active company set"}, status=403)

    shipment = get_object_or_404(
        ClinShipment,
        id=shipment_id,
        clin__contract__company=company,
    )

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    plan, created = ShipmentPaymentPlan.objects.get_or_create(shipment=shipment)

    update_fields = []

    if "planned_pay_date" in data:
        val = data["planned_pay_date"]
        if val == "":
            val = None
        plan.planned_pay_date = val
        update_fields.append("planned_pay_date")

    if "note" in data:
        plan.note = data["note"]
        update_fields.append("note")

    if "on_hold" in data:
        plan.on_hold = bool(data["on_hold"])
        update_fields.append("on_hold")

    plan.modified_by = request.user
    update_fields.append("modified_by")
    update_fields.append("modified_on")
    plan.save(update_fields=update_fields)

    p_date = plan.planned_pay_date.isoformat() if plan.planned_pay_date else None

    return JsonResponse({
        "success": True,
        "planned_pay_date": p_date,
        "note": plan.note,
        "on_hold": plan.on_hold,
    })
