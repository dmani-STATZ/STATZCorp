"""
Competitor award aggregation for the Competitors Numbers watchlist page.
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Min, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from sales.models import DibbsAward

_EARLIEST_AWARD_DATE_CACHE_KEY = "competitor_stats:earliest_award_date"
_EARLIEST_AWARD_DATE_CACHE_TTL = 3600
_SENTINEL = object()

_EMPTY_STATS = {
    "week_count": 0,
    "week_total": Decimal("0"),
    "month_count": 0,
    "month_total": Decimal("0"),
    "quarter_count": 0,
    "quarter_total": Decimal("0"),
    "year_count": 0,
    "year_total": Decimal("0"),
}


def get_calendar_bounds(reference_date=None):
    """
    Return (start, end) date tuples for week, month, quarter, and year.

    Week starts Monday. Quarter uses standard calendar quarters
    (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec) — NOT government fiscal year.
    """
    today = reference_date or timezone.now().date()

    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    month_start = today.replace(day=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])

    quarter_index = (today.month - 1) // 3
    quarter_start_month = quarter_index * 3 + 1
    quarter_start = date(today.year, quarter_start_month, 1)
    quarter_end_month = quarter_start_month + 2
    quarter_end = date(
        today.year,
        quarter_end_month,
        monthrange(today.year, quarter_end_month)[1],
    )

    year_start = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)

    return {
        "week": (week_start, week_end),
        "month": (month_start, month_end),
        "quarter": (quarter_start, quarter_end),
        "year": (year_start, year_end),
    }


def _bucket_filter(bounds, bucket_key):
    start, end = bounds[bucket_key]
    return Q(award_date__gte=start, award_date__lte=end)


def get_competitor_stats(cage_codes):
    """
    Single-query aggregation of award counts and dollar totals per CAGE code
    across week / month / quarter / year buckets (non-faux awards only).
    """
    normalized = [c for c in cage_codes if c]
    if not normalized:
        return {}

    bounds = get_calendar_bounds()
    week_q = _bucket_filter(bounds, "week")
    month_q = _bucket_filter(bounds, "month")
    quarter_q = _bucket_filter(bounds, "quarter")
    year_q = _bucket_filter(bounds, "year")

    rows = (
        DibbsAward.objects.filter(awardee_cage__in=normalized, is_faux=False)
        .values("awardee_cage")
        .annotate(
            week_count=Count("id", filter=week_q),
            week_total=Coalesce(
                Sum("total_contract_price", filter=week_q),
                Value(Decimal("0")),
            ),
            month_count=Count("id", filter=month_q),
            month_total=Coalesce(
                Sum("total_contract_price", filter=month_q),
                Value(Decimal("0")),
            ),
            quarter_count=Count("id", filter=quarter_q),
            quarter_total=Coalesce(
                Sum("total_contract_price", filter=quarter_q),
                Value(Decimal("0")),
            ),
            year_count=Count("id", filter=year_q),
            year_total=Coalesce(
                Sum("total_contract_price", filter=year_q),
                Value(Decimal("0")),
            ),
        )
    )

    result = {cage: dict(_EMPTY_STATS) for cage in normalized}
    for row in rows:
        cage = row["awardee_cage"]
        if cage not in result:
            continue
        result[cage] = {
            "week_count": row["week_count"],
            "week_total": row["week_total"] or Decimal("0"),
            "month_count": row["month_count"],
            "month_total": row["month_total"] or Decimal("0"),
            "quarter_count": row["quarter_count"],
            "quarter_total": row["quarter_total"] or Decimal("0"),
            "year_count": row["year_count"],
            "year_total": row["year_total"] or Decimal("0"),
        }
    return result


def get_earliest_award_date():
    """Earliest non-faux award_date in DibbsAward, cached for one hour."""
    cached = cache.get(_EARLIEST_AWARD_DATE_CACHE_KEY, _SENTINEL)
    if cached is not _SENTINEL:
        return cached

    earliest = DibbsAward.objects.filter(is_faux=False).aggregate(
        min_date=Min("award_date")
    )["min_date"]
    cache.set(_EARLIEST_AWARD_DATE_CACHE_KEY, earliest, _EARLIEST_AWARD_DATE_CACHE_TTL)
    return earliest
