"""
Supplier-related views: backfill, list, detail, add/remove NSN and FSC capabilities.
"""
import traceback

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods, require_POST
from django.db.models import Count, Q
from django.contrib import messages
from django.urls import reverse

from suppliers.models import Supplier
from sales.models import (
    SupplierNSN,
    SupplierFSC,
    SupplierQuote,
    SupplierRFQ,
)
from sales.services.matching import backfill_nsn_from_contracts


def _staff_required(user):
    return user.is_authenticated and user.is_staff


@login_required
def supplier_list(request):
    """Search suppliers; filter by has_nsn=1. Context: suppliers with nsn_count, fsc_count."""
    q = (request.GET.get("q") or "").strip()
    has_nsn = request.GET.get("has_nsn") == "1"

    suppliers = Supplier.objects.filter(archived=False).annotate(
        nsn_count=Count("nsn_capabilities", distinct=True),
        fsc_count=Count("fsc_capabilities", distinct=True),
        quote_count=Count("dibbs_quotes", distinct=True),
    )
    if q:
        suppliers = suppliers.filter(
            Q(name__icontains=q) | Q(cage_code__icontains=q)
        )
    if has_nsn:
        suppliers = suppliers.filter(nsn_count__gt=0)
    suppliers = suppliers.order_by("name")[:200]

    return render(request, "sales/suppliers/list.html", {
        "suppliers": suppliers,
        "q": q,
        "has_nsn": has_nsn,
    })


@login_required
def supplier_detail(request, supplier_id):
    """Supplier profile with tabs: Profile, Capabilities, Quote History."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    nsn_capabilities = SupplierNSN.objects.filter(supplier=supplier).order_by("-match_score")
    fsc_capabilities = SupplierFSC.objects.filter(supplier=supplier)
    quote_history = SupplierQuote.objects.filter(supplier=supplier).select_related("line__solicitation").order_by("-quote_date")[:20]
    rfq_history = SupplierRFQ.objects.filter(supplier=supplier).select_related("line__solicitation").order_by("-sent_at")[:20]

    return render(request, "sales/suppliers/detail.html", {
        "supplier": supplier,
        "nsn_capabilities": nsn_capabilities,
        "fsc_capabilities": fsc_capabilities,
        "quote_history": quote_history,
        "rfq_history": rfq_history,
    })


@login_required
@require_http_methods(["GET", "POST"])
def supplier_add_nsn(request, supplier_id):
    """GET: form (nsn, match_score, notes). POST: create SupplierNSN with source=manual."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    errors = {}

    if request.method == "POST":
        nsn_raw = (request.POST.get("nsn") or "").strip().replace("-", "")
        match_score = request.POST.get("match_score", "1.0").strip()
        notes = (request.POST.get("notes") or "").strip()[:255] or None

        if len(nsn_raw) != 13 or not nsn_raw.isdigit():
            errors["nsn"] = "NSN must be 13 digits (hyphens optional)."
        else:
            nsn_formatted = f"{nsn_raw[0:4]}-{nsn_raw[4:6]}-{nsn_raw[6:9]}-{nsn_raw[9:13]}"
            SupplierNSN.objects.get_or_create(
                supplier=supplier,
                nsn=nsn_formatted,
                defaults={"source": "manual", "match_score": float(match_score or 1.0), "notes": notes},
            )
            messages.success(request, f"NSN {nsn_formatted} added.")
            return redirect("sales:supplier_detail", supplier_id=supplier.pk)

    return render(request, "sales/suppliers/add_nsn.html", {
        "supplier": supplier,
        "errors": errors,
    })


@login_required
@require_http_methods(["GET", "POST"])
def supplier_add_fsc(request, supplier_id):
    """GET: form (fsc_code, notes). POST: get_or_create SupplierFSC."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    errors = {}

    if request.method == "POST":
        fsc_code = (request.POST.get("fsc_code") or "").strip()[:4]
        notes = (request.POST.get("notes") or "").strip()[:255] or None
        if len(fsc_code) != 4:
            errors["fsc_code"] = "FSC code must be 4 characters."
        else:
            SupplierFSC.objects.get_or_create(
                supplier=supplier,
                fsc_code=fsc_code,
                defaults={"notes": notes},
            )
            messages.success(request, f"FSC {fsc_code} added.")
            return redirect("sales:supplier_detail", supplier_id=supplier.pk)

    return render(request, "sales/suppliers/add_fsc.html", {
        "supplier": supplier,
        "errors": errors,
    })


@login_required
@require_POST
def supplier_remove_nsn(request, supplier_id):
    """POST: nsn_id. Delete SupplierNSN. Redirect to supplier_detail."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    nsn_id = request.POST.get("nsn_id")
    if nsn_id:
        SupplierNSN.objects.filter(supplier=supplier, pk=nsn_id).delete()
        messages.success(request, "NSN capability removed.")
    return redirect("sales:supplier_detail", supplier_id=supplier.pk)


@login_required
@require_POST
def supplier_remove_fsc(request, supplier_id):
    """POST: fsc_id. Delete SupplierFSC. Redirect to supplier_detail."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    fsc_id = request.POST.get("fsc_id")
    if fsc_id:
        SupplierFSC.objects.filter(supplier=supplier, pk=fsc_id).delete()
        messages.success(request, "FSC capability removed.")
    return redirect("sales:supplier_detail", supplier_id=supplier.pk)


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
