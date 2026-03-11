from sales.models import SupplierRFQ
from django.utils import timezone


def rfq_counts(request):
    if not request.user.is_authenticated:
        return {}
    overdue = SupplierRFQ.objects.filter(
        status='SENT',
        line__solicitation__return_by_date__lt=timezone.now().date(),
    ).count()
    return {'overdue_rfq_count': overdue}
