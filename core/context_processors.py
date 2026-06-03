def api_budget(request):
    if not request.user.is_authenticated:
        return {}
    from core.models import APIBudget, APIUsageLog
    from django.utils import timezone
    budget = APIBudget.get()
    today = timezone.now().date()
    calls_today = APIUsageLog.objects.filter(timestamp__date=today).count()
    return {
        "api_budget": budget,
        "api_budget_calls_today": calls_today,
    }
