"""
Real dashboard with live counts.
"""
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Exists, OuterRef, Prefetch
from django.shortcuts import render
from django.utils import timezone

from sales.models import ImportBatch, Solicitation, SolicitationLine, SupplierMatch

# Pipeline counts exclude terminal / hidden-from-workflow statuses (see sales/CONTEXT.md dashboard).
TERMINAL_STATUSES = ["Archived", "WON", "LOST", "NO_BID"]

# Active pipeline for secondary stat tiles (must match Solicitation.STATUS_CHOICES values).
PIPELINE_STATUSES = [
    "New",
    "Active",
    "RFQ_PENDING",
    "RFQ_SENT",
    "QUOTING",
    "BID_READY",
    "BID_SUBMITTED",
    "RESEARCH",
]


def _row_to_dict(cursor):
    """Map first row to a dict using cursor.description column names."""
    row = cursor.fetchone()
    if row is None:
        return {}
    cols = [c[0] for c in cursor.description]
    return dict(zip(cols, row))


def _fetch_group_counts(cursor):
    """Build {key: n} from rows of (key, n); coerces counts to int."""
    return {
        k: int(v) if v is not None else 0
        for k, v in cursor.fetchall()
    }


@login_required
def dashboard(request):
    """
    Real dashboard with live counts.
    Context:
        today               — date (timezone-aware calendar day)
        latest_batch        — most recent ImportBatch or None
        counts_by_status    — status -> count for pipeline solicitations; ``New`` / ``RFQ_PENDING``
                              overridden for stat cards (see CONTEXT.md)
        counts_by_bucket    — dict of bucket -> count (all solicitations; legacy field)
        sdvosb_priority_count — pipeline sols (excludes TERMINAL_STATUSES) with set-aside ``S`` or ``R`` (top stat card)
        sdvosb_count        — pipeline (``PIPELINE_STATUSES``) sols with set-aside ``R`` (secondary tile / list link)
        hubzone_count       — pipeline sols with set-aside ``H`` (secondary tile)
        growth_count        — pipeline sols: set-aside set, not R/H/blank/N, with ≥1 SupplierMatch (secondary tile)
        urgent_count        — pipeline sols with return_by_date from today through +3 days inclusive
        recent_solicitations — 10 most recent non-Skip solicitations
        total_active        — pipeline solicitation count (excludes TERMINAL_STATUSES)
        wins_this_month     — distinct win pairs this month (non-faux awards in WeWonAward view)
    """
    today = timezone.now().date()
    latest_batch = ImportBatch.objects.order_by("-import_date").first()

    _t = ", ".join(["%s"] * len(TERMINAL_STATUSES))
    _p = ", ".join(["%s"] * len(PIPELINE_STATUSES))
    scalar_sql = f"""
        SELECT
            COUNT(CASE WHEN status NOT IN ({_t}) THEN 1 END) AS total_active,
            COUNT(CASE
                WHEN status NOT IN ({_t})
                    AND return_by_date >= CAST(GETUTCDATE() AS DATE)
                    AND return_by_date <= DATEADD(day, 3, CAST(GETUTCDATE() AS DATE))
                THEN 1 END) AS urgent_count,
            COUNT(CASE
                WHEN status NOT IN ({_t}) AND small_business_set_aside IN ('S', 'R')
                THEN 1 END) AS sdvosb_priority_count,
            COUNT(CASE
                WHEN status IN ({_p}) AND small_business_set_aside = 'R'
                THEN 1 END) AS sdvosb_count,
            COUNT(CASE
                WHEN status IN ({_p}) AND small_business_set_aside = 'H'
                THEN 1 END) AS hubzone_count,
            COUNT(CASE WHEN status = 'RFQ_PENDING' THEN 1 END) AS rfq_pending,
            (
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT a.award_basic_number, a.delivery_order_number
                    FROM dibbs_award a
                    INNER JOIN dibbs_we_won_awards w ON a.id = w.id
                    WHERE a.is_faux = 0
                      AND a.award_date >= DATEFROMPARTS(
                          YEAR(GETUTCDATE()), MONTH(GETUTCDATE()), 1
                      )
                ) AS wins_distinct
            ) AS wins_this_month
        FROM dibbs_solicitation
    """
    scalar_params = (
        *TERMINAL_STATUSES,
        *TERMINAL_STATUSES,
        *TERMINAL_STATUSES,
        *PIPELINE_STATUSES,
        *PIPELINE_STATUSES,
    )

    with connection.cursor() as cursor:
        cursor.execute(scalar_sql, scalar_params)
        scalars = _row_to_dict(cursor)

        cursor.execute("""
            SELECT ISNULL(SUM(solicitation_count), 0)
            FROM tbl_ImportBatch
            WHERE CAST(imported_at AS DATE) = CAST(GETUTCDATE() AS DATE)
        """)
        row = cursor.fetchone()
        new_today = int(row[0]) if row and row[0] is not None else 0

        status_sql = f"""
            SELECT status, COUNT(*) AS n
            FROM dibbs_solicitation
            WHERE status NOT IN ({_t})
            GROUP BY status
        """
        cursor.execute(status_sql, TERMINAL_STATUSES)
        counts_by_status = _fetch_group_counts(cursor)

        bucket_sql = """
            SELECT bucket, COUNT(*) AS n
            FROM dibbs_solicitation
            GROUP BY bucket
        """
        cursor.execute(bucket_sql)
        counts_by_bucket = _fetch_group_counts(cursor)

    # Normalize keys from DB driver (e.g. case) and coerce counts to int
    def _int(d, key, default=0):
        for k, v in d.items():
            if k and k.lower() == key.lower():
                return int(v) if v is not None else default
        return default

    total_active = _int(scalars, "total_active")
    urgent_count = _int(scalars, "urgent_count")
    sdvosb_priority_count = _int(scalars, "sdvosb_priority_count")
    sdvosb_count = _int(scalars, "sdvosb_count")
    hubzone_count = _int(scalars, "hubzone_count")
    rfq_pending = _int(scalars, "rfq_pending")
    wins_this_month = _int(scalars, "wins_this_month")

    counts_by_status["New"] = new_today
    counts_by_status["RFQ_PENDING"] = rfq_pending

    growth_count = (
        Solicitation.objects.filter(status__in=PIPELINE_STATUSES)
        .filter(small_business_set_aside__isnull=False)
        .exclude(small_business_set_aside__in=["R", "H", "", "N"])
        .filter(
            Exists(
                SupplierMatch.objects.filter(line__solicitation=OuterRef("pk")),
            ),
        )
        .count()
    )

    first_line_prefetch = Prefetch(
        "lines",
        queryset=SolicitationLine.objects.order_by("line_number", "id"),
        to_attr="prefetched_lines",
    )
    recent_solicitations = (
        Solicitation.objects.exclude(bucket="SKIP")
        .prefetch_related(first_line_prefetch)
        .order_by("-import_date", "return_by_date")[:10]
    )

    return render(
        request,
        "sales/dashboard.html",
        {
            "today": today,
            "latest_batch": latest_batch,
            "counts_by_status": counts_by_status,
            "counts_by_bucket": counts_by_bucket,
            "sdvosb_priority_count": sdvosb_priority_count,
            "sdvosb_count": sdvosb_count,
            "hubzone_count": hubzone_count,
            "growth_count": growth_count,
            "urgent_count": urgent_count,
            "recent_solicitations": recent_solicitations,
            "total_active": total_active,
            "wins_this_month": wins_this_month,
        },
    )
