"""Contract modification acknowledgement API."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from sales.models import DibbsAwardMod
from sales.services.contract_mods import acknowledge_contract_mod


@login_required
@require_POST
def acknowledge_contract_mod_view(request, pk: int):
    mod = get_object_or_404(DibbsAwardMod, pk=pk)
    mod = acknowledge_contract_mod(mod, request.user)
    name = ""
    if mod.acknowledged_by_id:
        full = (mod.acknowledged_by.get_full_name() or "").strip()
        name = full or mod.acknowledged_by.get_username()
    return JsonResponse(
        {
            "acknowledged_at": mod.acknowledged_at.isoformat() if mod.acknowledged_at else None,
            "acknowledged_by": name,
        }
    )
