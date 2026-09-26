"""DIBBS data dashboard -- freshness of each DIBBS feed at a glance."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from dibbs.models import AwardImportBatch, DibbsNotice, ImportBatch, Solicitation


@login_required
def dashboard(request):
    """GET /dibbs/ -- latest import batches and open-solicitation count."""
    today = timezone.now().date()
    context = {
        "open_solicitations": Solicitation.objects.filter(return_by_date__gte=today).count(),
        "recent_imports": ImportBatch.objects.order_by("-import_date", "-imported_at")[:7],
        "recent_award_batches": AwardImportBatch.objects.order_by("-award_date")[:7],
        "recent_notices": DibbsNotice.objects.order_by("-posted_date")[:5],
    }
    return render(request, "dibbs/dashboard.html", context)
