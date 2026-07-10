"""
Competitors Numbers — shared competitor CAGE watchlist and award stats.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from sales.models import CompanyCAGE, CompetitorWatchlist, SAMEntityCache
from sales.services.competitor_stats import (
    _EMPTY_STATS,
    get_competitor_stats,
    get_earliest_award_date,
)
from sales.services.no_quote import normalize_cage_code
from sales.services.sam_entity import get_or_fetch_cage


def _name_is_available(cache_record):
    if cache_record.fetch_error:
        return False
    raw = cache_record.raw_json or {}
    if not raw.get("found"):
        return False
    return bool((cache_record.entity_name or "").strip())


def _adder_display_name(user):
    if not user:
        return "Unknown user"
    full = user.get_full_name()
    return full.strip() if full and full.strip() else user.username


def _our_numbers_display_name(company_cage):
    """Resolve STATZ CAGE display name from CompanyCAGE (no SAM lookup)."""
    name = (company_cage.company_name or "").strip()
    if name:
        return name
    if company_cage.company_id:
        return (company_cage.company.name or "").strip()
    return ""


@login_required
def competitor_watchlist(request):
    """GET — render the shared competitor watchlist and award statistics."""
    our_cages = list(
        CompanyCAGE.objects.filter(is_active=True)
        .select_related("company")
        .order_by("-is_default", "cage_code")
    )
    our_cage_codes = [c.cage_code for c in our_cages]
    our_stats_map = get_competitor_stats(our_cage_codes)
    our_rows = []
    for company_cage in our_cages:
        display_name = _our_numbers_display_name(company_cage)
        our_rows.append(
            {
                "cage_code": company_cage.cage_code,
                "display_name": display_name,
                "name_available": bool(display_name),
                "stats": our_stats_map.get(
                    company_cage.cage_code, dict(_EMPTY_STATS)
                ),
            }
        )

    entries = list(
        CompetitorWatchlist.objects.select_related("added_by").order_by("-added_at")
    )
    cage_codes = [e.cage_code for e in entries]

    stats_map = get_competitor_stats(cage_codes)
    cache_records = SAMEntityCache.objects.filter(cage_code__in=cage_codes)
    cache_map = {r.cage_code: r for r in cache_records}

    rows = []
    for entry in entries:
        cache_record = cache_map.get(entry.cage_code)
        name_available = cache_record and _name_is_available(cache_record)
        rows.append(
            {
                "entry": entry,
                "display_name": (cache_record.entity_name or "").strip()
                if name_available
                else "",
                "name_available": name_available,
                "stats": stats_map.get(entry.cage_code, dict(_EMPTY_STATS)),
                "can_remove": entry.added_by_id == request.user.id,
            }
        )

    def _row_sort_key(row):
        return (row["display_name"] or row["entry"].cage_code).lower()

    my_rows = [r for r in rows if r["entry"].added_by_id == request.user.id]
    other_rows = [r for r in rows if r["entry"].added_by_id != request.user.id]
    my_rows.sort(key=_row_sort_key)
    other_rows.sort(key=_row_sort_key)
    ordered_rows = my_rows + other_rows

    context = {
        "page_title": "Competitors Numbers",
        "our_rows": our_rows,
        "rows": ordered_rows,
        "earliest_award_date": get_earliest_award_date(),
    }
    return render(request, "sales/competitor_watchlist.html", context)


@login_required
@require_POST
def competitor_watchlist_add(request):
    """POST — add a CAGE code to the shared watchlist."""
    raw_cage = request.POST.get("cage_code", "")
    cage_norm = normalize_cage_code(raw_cage)
    if not cage_norm:
        messages.warning(request, "Enter a valid CAGE code (up to 5 characters).")
        return redirect(reverse("sales:competitor_watchlist"))

    if CompanyCAGE.objects.filter(cage_code=cage_norm, is_active=True).exists():
        messages.warning(
            request,
            f"CAGE {cage_norm} is one of STATZ's own CAGE codes, not a competitor.",
        )
        return redirect(reverse("sales:competitor_watchlist"))

    existing = (
        CompetitorWatchlist.objects.select_related("added_by")
        .filter(cage_code=cage_norm)
        .first()
    )
    if existing:
        adder = _adder_display_name(existing.added_by)
        messages.warning(
            request,
            f"CAGE {cage_norm} is already on the watchlist (added by {adder}).",
        )
        return redirect(reverse("sales:competitor_watchlist"))

    CompetitorWatchlist.objects.create(cage_code=cage_norm, added_by=request.user)
    get_or_fetch_cage(cage_norm)
    messages.success(request, f"CAGE {cage_norm} added to the watchlist.")
    return redirect(reverse("sales:competitor_watchlist"))


@login_required
@require_POST
def competitor_watchlist_remove(request, pk):
    """POST — remove a watchlist entry (owner only)."""
    entry = get_object_or_404(CompetitorWatchlist, pk=pk)
    if entry.added_by_id != request.user.id:
        adder = _adder_display_name(entry.added_by)
        messages.error(
            request,
            f"Only {adder} can remove CAGE {entry.cage_code} from the watchlist.",
        )
        return redirect(reverse("sales:competitor_watchlist"))

    cage = entry.cage_code
    entry.delete()
    messages.success(request, f"CAGE {cage} removed from the watchlist.")
    return redirect(reverse("sales:competitor_watchlist"))


@login_required
@require_POST
def competitor_watchlist_refetch_name(request, pk):
    """POST — force a fresh SAM.gov name lookup for one watchlist CAGE."""
    entry = get_object_or_404(CompetitorWatchlist, pk=pk)
    cage = entry.cage_code
    cache_record = get_or_fetch_cage(cage, force_refresh=True)
    if _name_is_available(cache_record):
        name = (cache_record.entity_name or "").strip()
        messages.success(request, f"Name for CAGE {cage} updated: {name}.")
    else:
        messages.warning(
            request,
            f"Could not resolve a company name for CAGE {cage}. "
            "Try again later or check SAM.gov access.",
        )
    return redirect(reverse("sales:competitor_watchlist"))
