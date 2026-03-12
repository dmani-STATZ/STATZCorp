"""
SAM.gov entity lookup view — read-only, no DB writes.
"""
import json
import logging

import requests
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import render

from sales.services.sam_entity import lookup_cage

logger = logging.getLogger(__name__)


@login_required
def entity_lookup(request, cage_code):
    """
    GET /sales/entity/cage/<cage_code>/

    Calls lookup_cage() and renders a read-only info card.
    Degrades gracefully on API errors or missing config — no 500s.
    """
    cage_code = (cage_code or "").strip().upper()
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
