"""
Real dashboard with live counts.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from sales.models import Solicitation, ImportBatch, DibbsAward, WeWonAward

# Pipeline counts exclude terminal / hidden-from-workflow statuses (see sales/CONTEXT.md dashboard).
TERMINAL_STATUSES = ["Archived", "WON", "LOST", "NO_BID"]


@login_required
def dashboard(request):
    """
    Real dashboard with live counts.
    Context:
        today               — date (timezone-aware calendar day)
        latest_batch        — most recent ImportBatch or None
        counts_by_status    — status -> count for pipeline solicitations; ``New`` / ``RFQ_PENDING``
                              overridden for stat cards (see CONTEXT.md)
        counts_by_bucket    — dict of bucket -> count (all solicitations)
        sdvosb_count        — pipeline sols with SDVOSB set-aside ``S`` or ``R`` (stat card)
        urgent_count        — pipeline sols with return_by_date from today through +3 days inclusive
        recent_solicitations — 10 most recent non-Skip solicitations
        total_active        — pipeline solicitation count (excludes TERMINAL_STATUSES)
    """
    today = timezone.now().date()
    latest_batch = ImportBatch.objects.order_by("-import_date").first()
    pipeline_qs = Solicitation.objects.exclude(status__in=TERMINAL_STATUSES)

    counts_by_status = dict(
        pipeline_qs.values_list("status").annotate(n=Count("id")).values_list("status", "n")
    )
    counts_by_bucket = dict(
        Solicitation.objects.values_list("bucket").annotate(n=Count("id")).values_list("bucket", "n")
    )
    three_days_out = today + timedelta(days=3)
    urgent_count = pipeline_qs.filter(
        return_by_date__gte=today,
        return_by_date__lte=three_days_out,
    ).count()
    total_active = pipeline_qs.count()

    sdvosb_count = (
        Solicitation.objects.exclude(status__in=TERMINAL_STATUSES)
        .filter(small_business_set_aside__in=["S", "R"])
        .count()
    )
    new_today = Solicitation.objects.filter(import_batch__imported_at__date=today).count()
    rfq_pending = Solicitation.objects.filter(status="RFQ_PENDING").count()
    counts_by_status["New"] = new_today
    counts_by_status["RFQ_PENDING"] = rfq_pending

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
            "sdvosb_count": sdvosb_count,
            "urgent_count": urgent_count,
            "recent_solicitations": recent_solicitations,
            "total_active": total_active,
            "wins_this_month": wins_this_month,
        },
    )
