"""
SAM.gov entity lookup view — uses SAMEntityCache (30-day TTL) with optional force refresh.
"""
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from sales.models import NoQuoteCAGE
from sales.services.no_quote import normalize_cage_code
from sales.services.sam_entity import get_or_fetch_cage

logger = logging.getLogger(__name__)


def _address_to_modal_shape(addr):
    """Map lookup_cage 'address' / 'mailing_address' dict to modal JSON keys."""
    if not addr:
        return None
    return {
        "line1": addr.get("street") or "",
        "line2": addr.get("street2") or "",
        "city": addr.get("city") or "",
        "state": addr.get("state") or "",
        "zip": addr.get("zip") or "",
    }


def _entity_lookup_json_payload(record, cage_code):
    """
    Flat JSON for ?fmt=json (workbench SAM modal). HTTP 200 always.
    """
    cage_code = record.cage_code or cage_code
    days = record.days_since_fetch
    fetch_error = record.fetch_error
    base_meta = {
        "days_since_fetch": days,
        "fetch_error": fetch_error,
    }
    if fetch_error:
        err = (record.raw_json or {}).get("error") or "Lookup failed."
        return {
            **base_meta,
            "error": err,
            "name": None,
            "cage_code": cage_code,
            "website": None,
            "physical_address": None,
            "mailing_address": None,
        }

    data = record.raw_json or {}
    if not data.get("found"):
        return {
            **base_meta,
            "error": f"No entity found for CAGE {cage_code}.",
            "name": None,
            "cage_code": cage_code,
            "website": None,
            "physical_address": None,
            "mailing_address": None,
        }

    entity_url = (data.get("entity_url") or "").strip() or None
    return {
        **base_meta,
        "error": None,
        "name": data.get("legal_name") or "",
        "cage_code": data.get("cage_code") or cage_code,
        "website": entity_url,
        "physical_address": _address_to_modal_shape(data.get("address")),
        "mailing_address": _address_to_modal_shape(data.get("mailing_address")),
    }


@login_required
def entity_lookup(request, cage_code):
    """
    GET /sales/entity/cage/<cage_code>/

    Cache-first SAM lookup via get_or_fetch_cage(). Renders read-only info card.
    GET ?fmt=json returns structured JSON for the workbench SAM modal (HTTP 200 always).
    GET ?refresh=1 forces a new SAM API fetch (HTML or JSON).
    """
    cage_code = (cage_code or "").strip().upper()
    cage_norm = normalize_cage_code(cage_code)
    is_no_quote = (
        bool(cage_norm)
        and NoQuoteCAGE.objects.filter(cage_code=cage_norm, is_active=True).exists()
    )

    force = request.GET.get("refresh") == "1"
    cache_record = get_or_fetch_cage(cage_code, force_refresh=force)

    if request.GET.get("fmt") == "json":
        return JsonResponse(_entity_lookup_json_payload(cache_record, cage_code))

    context = {
        "cage_code": cage_code,
        "is_no_quote": is_no_quote,
        "cache_record": cache_record,
        "days_since_fetch": cache_record.days_since_fetch,
        "fetch_error": cache_record.fetch_error,
    }

    if cache_record.fetch_error:
        context["error"] = (cache_record.raw_json or {}).get("error") or (
            "SAM.gov lookup failed. Please try again later."
        )
    else:
        context["entity"] = cache_record.raw_json or {}
        if request.user.is_staff and context["entity"].get("debug_raw_json") is not None:
            context["debug_raw"] = json.dumps(
                context["entity"].get("debug_raw_json", {}),
                indent=2,
                default=str,
            )

    return render(request, "sales/entity_lookup.html", context)


@login_required
@require_POST
def entity_no_quote_add(request, cage_code):
    """POST: optional reason. Adds URL CAGE to NoQuoteCAGE if not already active."""
    cage_norm = normalize_cage_code(cage_code)
    if not cage_norm:
        messages.warning(request, "Invalid CAGE code.")
        return redirect(reverse("sales:entity_cage_lookup", kwargs={"cage_code": cage_code}))

    reason = (request.POST.get("reason") or "").strip()
    if NoQuoteCAGE.objects.filter(cage_code=cage_norm, is_active=True).exists():
        messages.warning(request, f"CAGE {cage_norm} is already on the No Quote list.")
        return redirect(reverse("sales:entity_cage_lookup", kwargs={"cage_code": cage_norm}))

    NoQuoteCAGE.objects.create(
        cage_code=cage_norm,
        reason=reason,
        added_by=request.user,
        is_active=True,
    )
    messages.success(request, f"CAGE {cage_norm} added to the No Quote list.")
    return redirect(reverse("sales:entity_cage_lookup", kwargs={"cage_code": cage_norm}))
