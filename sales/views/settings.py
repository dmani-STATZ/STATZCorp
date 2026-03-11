"""
Settings views — CompanyCAGE management.
URL: /sales/settings/
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from sales.models import CompanyCAGE


@login_required
def settings_index(request):
    """Settings landing page — redirects to CAGE list."""
    return redirect("sales:settings_cages")


@login_required
def settings_cages(request):
    """List all CompanyCAGE records."""
    cages = CompanyCAGE.objects.order_by("-is_default", "cage_code")
    return render(request, "sales/settings/cages.html", {"cages": cages})


@login_required
def settings_cage_add(request):
    """Add a new CompanyCAGE record."""
    if request.method == "POST":
        cage = _cage_from_post(request.POST)
        cage.save()
        if cage.is_default:
            CompanyCAGE.objects.exclude(pk=cage.pk).update(is_default=False)
        messages.success(request, f"CAGE {cage.cage_code} added.")
        return redirect("sales:settings_cages")
    context = {
        "cage": None,
        "action": "Add",
        "sb_representations_choices": _get_sb_representations_choices(),
        "affirmative_choices": _get_affirmative_choices(),
        "prev_contracts_choices": _get_prev_contracts_choices(),
    }
    return render(request, "sales/settings/cage_form.html", context)


@login_required
def settings_cage_edit(request, cage_id):
    """Edit an existing CompanyCAGE record."""
    cage = get_object_or_404(CompanyCAGE, pk=cage_id)
    if request.method == "POST":
        _cage_from_post(request.POST, instance=cage)
        cage.save()
        if cage.is_default:
            CompanyCAGE.objects.exclude(pk=cage.pk).update(is_default=False)
        messages.success(request, f"CAGE {cage.cage_code} updated.")
        return redirect("sales:settings_cages")
    context = {
        "cage": cage,
        "action": "Edit",
        "sb_representations_choices": _get_sb_representations_choices(),
        "affirmative_choices": _get_affirmative_choices(),
        "prev_contracts_choices": _get_prev_contracts_choices(),
    }
    return render(request, "sales/settings/cage_form.html", context)


def _get_sb_representations_choices():
    """Return list of (code, description) tuples for Small Business Set-Aside Code (BQ col 13)."""
    return [
        ("Y", "Y - Small Business Set-Aside"),
        ("H", "H - HUBZone Set-Aside"),
        ("R", "R - Service Disabled Veteran-Owned Small Business (SDVOSB)"),
        ("L", "L - Woman-Owned Small Business (WOSB) Set-Aside"),
        ("A", "A - 8(a) Set-Aside"),
        ("E", "E - Economically Disadvantaged Woman-Owned (EDWOSB)"),
        ("N", "N - Unrestricted/Not Set-Aside"),
    ]


def _get_affirmative_choices():
    """Return list of (code, description) tuples for Affirmative Action Compliance Code (BQ col 21)."""
    return [
        ("Y6", "Developed and on File"),
        ("N6", "Not Developed and Not on File"),
        ("NH", "No Previous Contracts Subject to Requirements"),
        ("NA", "Not Applicable"),
    ]


def _get_prev_contracts_choices():
    """Return list of (code, description) tuples for Previous Contracts Compliance Code (BQ col 22)."""
    return [
        ("Y4", "Participated and Filed"),
        ("Y5", "Participated and Not Filed"),
        ("N4", "Not Participated"),
        ("NA", "Not Applicable"),
    ]


def _cage_from_post(data, instance=None):
    """Populate a CompanyCAGE from POST data. Returns unsaved instance."""
    cage = instance or CompanyCAGE()
    cage.cage_code = data.get("cage_code", "").strip().upper()
    cage.company_name = data.get("company_name", "").strip()
    cage.sb_representations_code = data.get("sb_representations_code", "N").strip()
    cage.affirmative_action_code = data.get("affirmative_action_code", "Y6").strip()
    cage.previous_contracts_code = data.get("previous_contracts_code", "Y4").strip()
    cage.alternate_disputes_resolution = data.get(
        "alternate_disputes_resolution", "A"
    ).strip()
    cage.default_fob_point = data.get("default_fob_point", "D").strip()
    cage.default_payment_terms = data.get("default_payment_terms", "1").strip()
    cage.default_child_labor_code = data.get("default_child_labor_code", "N").strip()
    cage.default_markup_pct = data.get("default_markup_pct", "3.50") or "3.50"
    cage.smtp_reply_to = data.get("smtp_reply_to", "").strip() or None
    cage.is_default = "is_default" in data
    cage.is_active = "is_active" in data
    return cage
