"""
Settings views — CompanyCAGE management.
URL: /dibbs/settings/
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from dibbs.forms import CompanyCAGEForm
from dibbs.models import CompanyCAGE


@login_required
def settings_index(request):
    """Settings landing page — redirects to CAGE list."""
    return redirect("dibbs:settings_cages")


@login_required
def settings_cages(request):
    """List all CompanyCAGE records."""
    cages = CompanyCAGE.objects.select_related("company").order_by(
        "-is_default", "cage_code"
    )
    return render(request, "dibbs/settings/cages.html", {"cages": cages, "section": "settings"})


@login_required
def settings_cage_add(request):
    """Add a new CompanyCAGE record."""
    if request.method == "POST":
        form = CompanyCAGEForm(request.POST)
        if form.is_valid():
            cage = form.save()
            if cage.is_default:
                CompanyCAGE.objects.exclude(pk=cage.pk).update(is_default=False)
            messages.success(request, f"CAGE {cage.cage_code} added.")
            return redirect("dibbs:settings_cages")
    else:
        form = CompanyCAGEForm()
    context = {
        "form": form,
        "action": "Add",
        "section": "settings",
    }
    return render(request, "dibbs/settings/cage_form.html", context)


@login_required
def settings_cage_edit(request, cage_id):
    """Edit an existing CompanyCAGE record."""
    cage = get_object_or_404(CompanyCAGE, pk=cage_id)
    if request.method == "POST":
        form = CompanyCAGEForm(request.POST, instance=cage)
        if form.is_valid():
            cage = form.save()
            if cage.is_default:
                CompanyCAGE.objects.exclude(pk=cage.pk).update(is_default=False)
            messages.success(request, f"CAGE {cage.cage_code} updated.")
            return redirect("dibbs:settings_cages")
    else:
        form = CompanyCAGEForm(instance=cage)
    context = {
        "form": form,
        "action": "Edit",
        "section": "settings",
    }
    return render(request, "dibbs/settings/cage_form.html", context)


# ---------- Email Templates ----------
