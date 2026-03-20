"""
Supplier-related views: backfill, list, detail, add/remove NSN and FSC capabilities.
"""
import traceback

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods, require_POST
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.contrib import messages
from django.urls import reverse

from suppliers.models import Supplier
from sales.models import (
    SupplierNSN,
    SupplierFSC,
    SupplierQuote,
    NoQuoteCAGE,
)
from sales.services.no_quote import normalize_cage_code
from sales.services.matching import backfill_nsn_from_contracts


def _staff_required(user):
    return user.is_authenticated and user.is_staff


@login_required
def supplier_list(request):
    """Lists suppliers with DIBBS capability data. GET q= search by name or cage_code. Paginated 50 per page."""
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
    suppliers = suppliers.order_by("name")
    paginator = Paginator(suppliers, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(request, "sales/suppliers/list.html", {
        "suppliers": page_obj,
        "q": q,
        "has_nsn": has_nsn,
        "page_obj": page_obj,
    })


@login_required
def supplier_detail(request, supplier_id):
    """3-tab detail: Profile, Capabilities, Quote History."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    nsn_capabilities = SupplierNSN.objects.filter(supplier=supplier).order_by("-match_score")
    fsc_capabilities = SupplierFSC.objects.filter(supplier=supplier).order_by("fsc_code")
    quote_history = (
        SupplierQuote.objects.filter(supplier=supplier)
        .select_related("line__solicitation", "rfq")
        .order_by("-quote_date")[:50]
    )
    active_tab = request.GET.get("tab", "profile")
    cage_norm = normalize_cage_code(supplier.cage_code)
    is_no_quote = (
        bool(cage_norm)
        and NoQuoteCAGE.objects.filter(cage_code=cage_norm, is_active=True).exists()
    )

    return render(request, "sales/suppliers/detail.html", {
        "supplier": supplier,
        "nsn_capabilities": nsn_capabilities,
        "fsc_capabilities": fsc_capabilities,
        "quote_history": quote_history,
        "active_tab": active_tab,
        "is_no_quote": is_no_quote,
    })


@login_required
@require_http_methods(["GET", "POST"])
def supplier_add_nsn(request, supplier_id):
    """GET: form to add NSN. POST: validate 13-digit NSN, get_or_create with source=manual, match_score=100."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    error = None

    if request.method == "POST":
        nsn_raw = (request.POST.get("nsn") or "").strip().replace("-", "").replace(" ", "")
        part_number = (request.POST.get("part_number") or "").strip()[:100] or None
        notes = (request.POST.get("notes") or "").strip()[:255] or None

        if len(nsn_raw) != 13 or not nsn_raw.isdigit():
            error = "NSN must be 13 digits (hyphens/spaces optional)."
        else:
            cleaned_nsn = f"{nsn_raw[0:4]}-{nsn_raw[4:6]}-{nsn_raw[6:9]}-{nsn_raw[9:13]}"
            SupplierNSN.objects.get_or_create(
                supplier=supplier,
                nsn=cleaned_nsn,
                defaults={
                    "part_number": part_number,
                    "notes": notes,
                    "source": "manual",
                    "match_score": 100,
                },
            )
            messages.success(request, f"NSN {cleaned_nsn} added.")
            return redirect(reverse("sales:supplier_detail", args=[supplier.pk]) + "?tab=capabilities")

    return render(request, "sales/suppliers/add_nsn.html", {
        "supplier": supplier,
        "error": error,
        "errors": {"nsn": error} if error else {},
    })


@login_required
@require_http_methods(["GET", "POST"])
def supplier_add_fsc(request, supplier_id):
    """GET: form to add FSC. POST: validate 4 alphanumeric (uppercase), get_or_create. Redirect tab=capabilities."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    error = None

    if request.method == "POST":
        fsc_code = (request.POST.get("fsc_code") or "").strip()[:4].upper()
        notes = (request.POST.get("notes") or "").strip()[:255] or None
        if len(fsc_code) != 4 or not fsc_code.isalnum():
            error = "FSC code must be exactly 4 alphanumeric characters."
        else:
            SupplierFSC.objects.get_or_create(
                supplier=supplier,
                fsc_code=fsc_code,
                defaults={"notes": notes},
            )
            messages.success(request, f"FSC {fsc_code} added.")
            return redirect(reverse("sales:supplier_detail", args=[supplier.pk]) + "?tab=capabilities")

    return render(request, "sales/suppliers/add_fsc.html", {
        "supplier": supplier,
        "error": error,
        "errors": {"fsc_code": error} if error else {},
    })


@login_required
@require_POST
def supplier_remove_nsn(request, supplier_id):
    """POST: nsn_id. Delete SupplierNSN if belongs to this supplier. Redirect to supplier_detail?tab=capabilities."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    nsn_id = request.POST.get("nsn_id")
    if nsn_id:
        SupplierNSN.objects.filter(supplier=supplier, pk=nsn_id).delete()
        messages.success(request, "NSN capability removed.")
    return redirect(reverse("sales:supplier_detail", args=[supplier.pk]) + "?tab=capabilities")


@login_required
@require_POST
def supplier_remove_fsc(request, supplier_id):
    """POST: fsc_id. Delete SupplierFSC if belongs to this supplier. Redirect to supplier_detail?tab=capabilities."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    fsc_id = request.POST.get("fsc_id")
    if fsc_id:
        SupplierFSC.objects.filter(supplier=supplier, pk=fsc_id).delete()
        messages.success(request, "FSC capability removed.")
    return redirect(reverse("sales:supplier_detail", args=[supplier.pk]) + "?tab=capabilities")


@login_required
@require_POST
def supplier_no_quote_add(request, supplier_id):
    """
    POST: optional reason. Adds supplier's CAGE to NoQuoteCAGE if not already active.
    """
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    cage_norm = normalize_cage_code(supplier.cage_code)
    if not cage_norm:
        messages.warning(request, "This supplier has no CAGE code on file.")
        return redirect(reverse("sales:supplier_detail", args=[supplier.pk]))

    reason = (request.POST.get("reason") or "").strip()
    if NoQuoteCAGE.objects.filter(cage_code=cage_norm, is_active=True).exists():
        messages.warning(request, f"CAGE {cage_norm} is already on the No Quote list.")
        return redirect(reverse("sales:supplier_detail", args=[supplier.pk]))

    NoQuoteCAGE.objects.create(
        cage_code=cage_norm,
        reason=reason,
        added_by=request.user,
        is_active=True,
    )
    messages.success(request, f"CAGE {cage_norm} added to the No Quote list.")
    return redirect(reverse("sales:supplier_detail", args=[supplier.pk]))


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
