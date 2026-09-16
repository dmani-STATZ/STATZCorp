from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from sales.models import DibbsNotice
from sales.services.dibbs_notices import get_recent_notice_count


@login_required
@require_http_methods(["GET"])
def dibbs_notices_page(request):
    """Render the dedicated portal page; notice rows load from the existing API."""
    return render(request, "sales/dibbs_notices.html")


@login_required
@require_http_methods(["GET"])
def dibbs_notices_api(request):
    """
    JSON endpoint returning DIBBS notices for the portal home page.
    Returns up to 30 notices (most recent first) and a count of notices
    posted within the last 7 days.
    """
    notices = list(
        DibbsNotice.objects.order_by("-posted_date").values(
            "title", "external_url", "posted_date"
        )[:30]
    )
    recent_count = get_recent_notice_count()

    for n in notices:
        n["posted_date"] = n["posted_date"].isoformat()

    return JsonResponse({"notices": notices, "recent_count": recent_count})
