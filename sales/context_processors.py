from sales.models import SupplierRFQ
from django.core.cache import cache
from django.utils import timezone

from sales.services.dibbs_notices import get_recent_notice_count
from sales.views.solicitations import COST_OF_MONEY_DAILY_RATE

_DIBBS_NOTICE_COUNT_CACHE_KEY = "sales:dibbs_notice_recent_count:v1"
_DIBBS_NOTICE_COUNT_CACHE_TTL = 1800


def dibbs_notice_count(request):
    """Expose the cached recent DIBBS notice count to authenticated templates."""
    if not request.user.is_authenticated:
        return {"dibbs_notice_recent_count": 0}
    count = cache.get(_DIBBS_NOTICE_COUNT_CACHE_KEY)
    if count is None:
        count = get_recent_notice_count()
        cache.set(
            _DIBBS_NOTICE_COUNT_CACHE_KEY,
            count,
            _DIBBS_NOTICE_COUNT_CACHE_TTL,
        )
    return {"dibbs_notice_recent_count": count}


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
