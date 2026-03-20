"""
SAM.gov entity lookup view — read-only, no DB writes.
"""
import json
import logging

import requests
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.shortcuts import render

from sales.services.sam_entity import lookup_cage

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


def _entity_lookup_json(cage_code):
    """
    Structured JSON for the solicitation detail SAM modal (?fmt=json).
    Always HTTP 200; failures use {"error": "..."} so the client can prefill manually.
    """
    try:
        data = lookup_cage(cage_code)
    except ImproperlyConfigured as exc:
        return JsonResponse(
            {
                "error": str(exc),
                "name": None,
                "cage_code": cage_code,
                "website": None,
                "physical_address": None,
                "mailing_address": None,
            }
        )
    except requests.RequestException as exc:
        logger.warning("entity_lookup JSON: API error for CAGE %s: %s", cage_code, exc)
        return JsonResponse(
            {
                "error": str(exc),
                "name": None,
                "cage_code": cage_code,
                "website": None,
                "physical_address": None,
                "mailing_address": None,
            }
        )
    except Exception as exc:
        logger.exception("entity_lookup JSON: unexpected error for CAGE %s", cage_code)
        return JsonResponse(
            {
                "error": "An unexpected error occurred while looking up this CAGE code.",
                "name": None,
                "cage_code": cage_code,
                "website": None,
                "physical_address": None,
                "mailing_address": None,
            }
        )

    if not data.get("found"):
        return JsonResponse(
            {
                "error": f"No entity found for CAGE {cage_code}.",
                "name": None,
                "cage_code": cage_code,
                "website": None,
                "physical_address": None,
                "mailing_address": None,
            }
        )

    entity_url = (data.get("entity_url") or "").strip() or None
    return JsonResponse(
        {
            "error": None,
            "name": data.get("legal_name") or "",
            "cage_code": data.get("cage_code") or cage_code,
            "website": entity_url,
            "physical_address": _address_to_modal_shape(data.get("address")),
            "mailing_address": _address_to_modal_shape(data.get("mailing_address")),
        }
    )


@login_required
def entity_lookup(request, cage_code):
    """
    GET /sales/entity/cage/<cage_code>/

    Calls lookup_cage() and renders a read-only info card.
    Degrades gracefully on API errors or missing config — no 500s.

    GET ?fmt=json returns structured JSON for the SAM “Add & Queue” modal (HTTP 200 always).
    """
    cage_code = (cage_code or "").strip().upper()

    if request.GET.get("fmt") == "json":
        return _entity_lookup_json(cage_code)

    context = {"cage_code": cage_code}

    try:
        data = lookup_cage(cage_code)
        context["entity"] = data
        if request.user.is_staff:
            context["debug_raw"] = json.dumps(data.get("debug_raw_json", {}), indent=2, default=str)
    except ImproperlyConfigured as exc:
        logger.warning("entity_lookup: %s", exc)
        context["error"] = (
            "SAM.gov lookup is not configured. "
            "Please ask your administrator to set SAM_API_KEY in settings."
        )
    except requests.RequestException as exc:
        logger.warning("entity_lookup: API error for CAGE %s: %s", cage_code, exc)
        context["error"] = str(exc)
    except Exception as exc:
        logger.exception("entity_lookup: unexpected error for CAGE %s", cage_code)
        context["error"] = (
            "An unexpected error occurred while looking up this CAGE code. "
            "Please try again later."
        )

    return render(request, "sales/entity_lookup.html", context)
