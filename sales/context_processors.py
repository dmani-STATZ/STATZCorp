from sales.models import SupplierRFQ
from django.utils import timezone

from sales.views.solicitations import COST_OF_MONEY_DAILY_RATE


def solicitation_nav_tools(request):
    """Solicitation URL prefix: list, workbench, closed, mass pass, review queues, etc."""
    path = getattr(request, "path", "") or ""
    show = path.startswith("/sales/solicitations")
    ctx = {"show_cost_of_money_calculator": show}
    if show:
        ctx["cost_of_money_rate"] = COST_OF_MONEY_DAILY_RATE
    return ctx


def rfq_counts(request):
    if not request.user.is_authenticated:
        return {}
    overdue = SupplierRFQ.objects.filter(
        status='SENT',
        line__solicitation__return_by_date__lt=timezone.now().date(),
    ).count()
    return {'overdue_rfq_count': overdue}
