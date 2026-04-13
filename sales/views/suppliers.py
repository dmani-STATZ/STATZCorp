"""
Supplier-related views: list, detail, add/remove NSN and FSC capabilities.
"""
import re
from io import StringIO

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from suppliers.models import Supplier
from sales.models import (
    SupplierNSN,
    SupplierNSNScored,
    SupplierFSC,
    SupplierQuote,
    NoQuoteCAGE,
)
from sales.services.no_quote import normalize_cage_code


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


def _supplier_capabilities_redirect(supplier_pk):
    return redirect(reverse("sales:supplier_detail", args=[supplier_pk]) + "?tab=capabilities")


@login_required
def supplier_detail(request, supplier_id):
    """3-tab detail: Profile, Capabilities, Quote History."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    nsn_capabilities = SupplierNSNScored.objects.filter(supplier=supplier).order_by(
        "-match_score", "nsn"
    )
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
    """Bulk paste NSNs (one per line); normalize, validate, get_or_create."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)

    if request.method == "POST":
        raw = request.POST.get("nsns", "")
        lines = raw.splitlines()
        error_list = []
        created_count = 0
        duplicate_count = 0
        valid_count = 0

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            normalized = line.replace("-", "").strip()
            if len(normalized) != 13 or not normalized.isdigit():
                error_list.append(raw_line.strip())
                continue
            valid_count += 1
            _obj, created = SupplierNSN.objects.get_or_create(
                supplier=supplier,
                nsn=normalized,
                defaults={"notes": "", "added_by": request.user},
            )
            if created:
                created_count += 1
            else:
                duplicate_count += 1

        if valid_count == 0:
            messages.error(request, "No valid NSNs to add. Enter one 13-digit NSN per line.")
            return _supplier_capabilities_redirect(supplier.pk)

        if created_count:
            messages.success(
                request,
                f"{created_count} NSN(s) added. {duplicate_count} duplicate(s) skipped.",
            )
        else:
            messages.success(
                request,
                f"0 NSN(s) added. {duplicate_count} duplicate(s) skipped.",
            )

        if error_list:
            preview = ", ".join(error_list[:20])
            if len(error_list) > 20:
                preview += f" … and {len(error_list) - 20} more"
            messages.warning(
                request,
                f"Invalid entries (not 13 digits): {preview}",
            )

        return _supplier_capabilities_redirect(supplier.pk)

    return render(request, "sales/suppliers/add_nsn.html", {
        "supplier": supplier,
    })


@login_required
@require_http_methods(["GET", "POST"])
def supplier_add_fsc(request, supplier_id):
    """Bulk paste FSC codes (one per line)."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)

    if request.method == "POST":
        raw = request.POST.get("fscs", "")
        lines = raw.splitlines()
        error_list = []
        created_count = 0
        duplicate_count = 0
        valid_count = 0

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            value = line.upper()
            if len(value) != 4 or not value.isalnum():
                error_list.append(raw_line.strip())
                continue
            valid_count += 1
            _obj, created = SupplierFSC.objects.get_or_create(
                supplier=supplier,
                fsc_code=value,
                defaults={"notes": ""},
            )
            if created:
                created_count += 1
            else:
                duplicate_count += 1

        if valid_count == 0:
            messages.error(
                request,
                "No valid FSC codes to add. Enter one 4-character alphanumeric code per line.",
            )
            return _supplier_capabilities_redirect(supplier.pk)

        if created_count:
            messages.success(
                request,
                f"{created_count} FSC(s) added. {duplicate_count} duplicate(s) skipped.",
            )
        else:
            messages.success(
                request,
                f"0 FSC(s) added. {duplicate_count} duplicate(s) skipped.",
            )

        if error_list:
            preview = ", ".join(error_list[:20])
            if len(error_list) > 20:
                preview += f" … and {len(error_list) - 20} more"
            messages.warning(
                request,
                f"Invalid entries (must be 4 alphanumeric characters): {preview}",
            )

        return _supplier_capabilities_redirect(supplier.pk)

    return render(request, "sales/suppliers/add_fsc.html", {
        "supplier": supplier,
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
    return _supplier_capabilities_redirect(supplier.pk)


@login_required
@require_POST
def supplier_remove_fsc(request, supplier_id):
    """POST: fsc_id. Delete SupplierFSC if belongs to this supplier. Redirect to supplier_detail?tab=capabilities."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    fsc_id = request.POST.get("fsc_id")
    if fsc_id:
        SupplierFSC.objects.filter(supplier=supplier, pk=fsc_id).delete()
        messages.success(request, "FSC capability removed.")
    return _supplier_capabilities_redirect(supplier.pk)


@staff_member_required
@require_POST
def refresh_match_counts_view(request):
    """On-demand refresh of Solicitation.match_count from the SQL view."""
    import traceback
    try:
        out = StringIO()
        call_command('refresh_match_counts', stdout=out)
        output = out.getvalue()
        match = re.search(r'(\d+)', output)
        updated = int(match.group(1)) if match else 0
        return JsonResponse({'status': 'ok', 'updated': updated})
    except Exception:
        error_detail = traceback.format_exc()
        return JsonResponse({'status': 'error', 'detail': error_detail}, status=500)


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
