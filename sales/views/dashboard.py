"""
Real dashboard with live counts.
"""
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render

from sales.models import Solicitation, ImportBatch, DibbsAward, WeWonAward


@login_required
def dashboard(request):
    """
    Real dashboard with live counts.
    Context:
        today               — date
        latest_batch        — most recent ImportBatch or None
        counts_by_status    — dict of status -> count for active solicitations
        counts_by_bucket    — dict of bucket -> count
        urgent_count        — solicitations with return_by_date within 3 days, not No-Bid/Won/Lost
        recent_solicitations — 10 most recent non-Skip solicitations
        total_active        — solicitations not in (NO_BID, WON, LOST)
    """
    today = date.today()
    latest_batch = ImportBatch.objects.order_by("-import_date").first()
    active_qs = Solicitation.objects.exclude(status__in=["NO_BID", "WON", "LOST"])

    counts_by_status = dict(
        active_qs.values_list("status").annotate(n=Count("id")).values_list("status", "n")
    )
    counts_by_bucket = dict(
        Solicitation.objects.values_list("bucket").annotate(n=Count("id")).values_list("bucket", "n")
    )
    urgent_count = active_qs.filter(
        return_by_date__lte=today + timedelta(days=3)
    ).count()
    total_active = active_qs.count()

    recent_solicitations = (
        Solicitation.objects.exclude(bucket="SKIP")
        .select_related("import_batch")
        .prefetch_related("lines")
        .order_by("-import_date", "return_by_date")[:10]
    )
    # Attach first_line for template
    for sol in recent_solicitations:
        sol.first_line = sol.lines.order_by("line_number", "id").first()

    month_start = today.replace(day=1)
    wins_this_month = (
        DibbsAward.objects
        .filter(id__in=WeWonAward.objects.values("id"))
        .filter(award_date__gte=month_start)
        .filter(is_faux=False)
        .values("award_basic_number", "delivery_order_number")
        .distinct()
        .count()
    )

    return render(
        request,
        "sales/dashboard.html",
        {
            "today": today,
            "latest_batch": latest_batch,
            "counts_by_status": counts_by_status,
            "counts_by_bucket": counts_by_bucket,
            "urgent_count": urgent_count,
            "recent_solicitations": recent_solicitations,
            "total_active": total_active,
            "wins_this_month": wins_this_month,
        },
    )
