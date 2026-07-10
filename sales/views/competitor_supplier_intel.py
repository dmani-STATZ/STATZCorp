"""
Supplier Intelligence — per-competitor view of role-tagged award entities.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, render

from sales.models import (
    CompetitorAwardEntity,
    CompetitorAwardParseStatus,
    CompetitorWatchlist,
    SAMEntityCache,
)
from sales.views.competitor_watchlist import _name_is_available

_ROLE_LABELS = dict(CompetitorAwardEntity.ROLE_CHOICES)


@login_required
def competitor_supplier_intel(request, cage_code):
    """GET — sourcing entities for one watched competitor CAGE."""
    cage = (cage_code or "").strip().upper()
    entry = get_object_or_404(CompetitorWatchlist, cage_code=cage)

    parse_qs = CompetitorAwardParseStatus.objects.filter(award__awardee_cage=cage)
    total_intel_count = parse_qs.count()

    entity_base = CompetitorAwardEntity.objects.filter(award__awardee_cage=cage)

    # Primary ranking: exclude buyer / payment-office DoDAACs.
    ranking_qs = entity_base.exclude(
        role__in=CompetitorAwardEntity.RANKING_EXCLUDED_ROLES
    )
    grouped = list(
        ranking_qs.values("code", "code_type", "role")
        .annotate(
            award_count=Count("award_id", distinct=True),
            latest_award_date=Max("award__award_date"),
            sample_source_note=Max("source_note"),
        )
        .order_by("-award_count", "role", "code")
    )

    # Awards parsed successfully but with no ranking-eligible entity.
    awards_with_ranking = set(
        ranking_qs.values_list("award_id", flat=True).distinct()
    )
    parsed_award_ids = set(parse_qs.values_list("award_id", flat=True))
    unresolved_count = len(parsed_award_ids - awards_with_ranking)

    # Other entities (BUYER / PAYMENT_OFFICE) for audit completeness.
    other_grouped = list(
        entity_base.filter(role__in=CompetitorAwardEntity.RANKING_EXCLUDED_ROLES)
        .values("code", "code_type", "role")
        .annotate(
            award_count=Count("award_id", distinct=True),
            latest_award_date=Max("award__award_date"),
            sample_source_note=Max("source_note"),
        )
        .order_by("role", "-award_count", "code")
    )

    cage_codes = [
        g["code"]
        for g in grouped + other_grouped
        if g["code_type"] == CompetitorAwardEntity.CODE_TYPE_CAGE
    ]
    cache_map = {}
    if cage_codes:
        cache_records = list(
            SAMEntityCache.objects.filter(cage_code__in=cage_codes)
        )
        cache_map = {r.cage_code: r for r in cache_records}

    competitor_cache = SAMEntityCache.objects.filter(cage_code=cage).first()
    competitor_name = ""
    if competitor_cache and _name_is_available(competitor_cache):
        competitor_name = (competitor_cache.entity_name or "").strip()

    # Printed names from entity rows (prefer non-blank; DoDAACs stay as-printed).
    printed_name_rows = list(
        entity_base.exclude(entity_name="")
        .values("code", "role")
        .annotate(sample_name=Max("entity_name"))
    )
    printed_names = {
        (r["code"], r["role"]): (r["sample_name"] or "").strip()
        for r in printed_name_rows
    }

    def _build_row(g):
        code = g["code"]
        role = g["role"]
        code_type = g["code_type"]
        printed = printed_names.get((code, role), "")
        cache_record = (
            cache_map.get(code)
            if code_type == CompetitorAwardEntity.CODE_TYPE_CAGE
            else None
        )
        name_available = bool(cache_record and _name_is_available(cache_record))
        sam_name = (
            (cache_record.entity_name or "").strip() if name_available else ""
        )
        display_name = sam_name or printed
        return {
            "code": code,
            "code_type": code_type,
            "role": role,
            "role_label": _ROLE_LABELS.get(role, role),
            "display_name": display_name,
            "name_available": bool(display_name),
            "source_note": (g.get("sample_source_note") or "").strip(),
            "award_count": g["award_count"],
            "latest_award_date": g["latest_award_date"],
        }

    suppliers = [_build_row(g) for g in grouped]
    other_entities = [_build_row(g) for g in other_grouped]

    context = {
        "page_title": f"Supplier Intelligence — {cage}",
        "entry": entry,
        "competitor_cage": cage,
        "competitor_name": competitor_name,
        "suppliers": suppliers,
        "other_entities": other_entities,
        "unresolved_count": unresolved_count,
        "total_intel_count": total_intel_count,
    }
    return render(request, "sales/competitor_supplier_intel.html", context)
