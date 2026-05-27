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
