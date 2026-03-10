"""
Supplier-related views (e.g. NSN backfill from contract history).
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods

from sales.services.matching import backfill_nsn_from_contracts


def _staff_required(user):
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(_staff_required)
@require_http_methods(["GET", "POST"])
def backfill_nsn(request):
    """
    GET:  show confirmation page
    POST: run backfill_nsn_from_contracts(), show results
    Dry-run option via ?dry_run=1 on GET or POST
    """
    dry_run = request.GET.get("dry_run") == "1" or (
        request.method == "POST" and request.POST.get("dry_run") == "1"
    )
    result = None

    if request.method == "POST":
        run_dry = "dry_run" in request.POST
        result = backfill_nsn_from_contracts(dry_run=run_dry)

    return render(
        request,
        "sales/suppliers/backfill_nsn.html",
        {
            "dry_run": dry_run,
            "result": result,
            "page_title": "Backfill NSN from Contract History",
        },
    )
