"""
Supplier-related views (e.g. NSN backfill from contract history).
"""
import traceback

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
    Dry-run option via POST field dry_run=1
    """
    result = None
    error = None
    run_dry = False

    if request.method == "POST":
        run_dry = "dry_run" in request.POST
        try:
            result = backfill_nsn_from_contracts(dry_run=run_dry)
        except Exception as e:
            error = {
                "message": str(e),
                "traceback": traceback.format_exc(),
            }

    return render(
        request,
        "sales/suppliers/backfill_nsn.html",
        {
            "dry_run": run_dry,
            "result": result,
            "error": error,
            "page_title": "Backfill NSN from Contract History",
        },
    )
