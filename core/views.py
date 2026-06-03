from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from core.health import run_readiness_check

_NO_STORE = {"Cache-Control": "no-store"}


@require_GET
def azure_health(request):
    """JSON readiness endpoint for Azure App Service health probes."""
    healthy, checks = run_readiness_check()
    status = "healthy" if healthy else "unhealthy"
    code = 200 if healthy else 503
    return JsonResponse(
        {"status": status, "checks": checks},
        status=code,
        headers=_NO_STORE,
    )


@require_GET
def health_plain(request):
    """Plain-text readiness endpoint; backward-compatible /health/ path."""
    healthy, _checks = run_readiness_check()
    body = "OK" if healthy else "UNAVAILABLE"
    code = 200 if healthy else 503
    return HttpResponse(body, content_type="text/plain", status=code, headers=_NO_STORE)


from decimal import Decimal, InvalidOperation
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils.timezone import now
from core.models import APIBudget

@login_required
@require_POST
def sync_api_budget(request):
    if not request.user.is_superuser:
        return JsonResponse({"success": False, "error": "Superuser permission required."}, status=403)
    
    new_balance_str = request.POST.get("new_balance")
    if new_balance_str is None:
        return JsonResponse({"success": False, "error": "Missing new_balance parameter."}, status=400)
    
    try:
        new_balance = Decimal(new_balance_str)
        if new_balance < 0:
            raise ValueError("Balance must be a positive number.")
    except (InvalidOperation, ValueError):
        return JsonResponse({"success": False, "error": "Please enter a valid positive balance."}, status=400)
        
    budget = APIBudget.get()
    budget.balance_usd = new_balance
    budget.last_sync_amount = new_balance
    budget.last_sync_at = now()
    budget.save(update_fields=['balance_usd', 'last_sync_amount', 'last_sync_at', 'updated_at'])
    
    return JsonResponse({"success": True, "new_balance": str(budget.balance_usd)})

