import re

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Min, Prefetch, Q, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from core.health import run_readiness_check
from contracts.models import Contract
from contracts.services.contract_number import normalize_contract_number
from products.models import Nsn
from products.nsn_utils import normalize_nsn, nsn_query_variants
from products.views import _suppliers_matching_cage
from sales.models import Solicitation, SolicitationLine
from suppliers.models import Supplier

_NO_STORE = {"Cache-Control": "no-store"}
_SEARCH_RESULT_LIMIT = 10
_CAGE_RE = re.compile(r"^[A-Za-z0-9]{5}$")


@require_GET
def azure_health(request):
    """JSON readiness endpoint for Azure App Service health probes."""
    healthy, checks = run_readiness_check()
    status = "healthy" if healthy else "unhealthy"
    code = 200 if healthy else 503
    return JsonResponse(
        {"status": status, "checks": checks},
        status=code,
        headers=_NO_STORE,
    )


@require_GET
def health_plain(request):
    """Plain-text readiness endpoint; backward-compatible /health/ path."""
    healthy, _checks = run_readiness_check()
    body = "OK" if healthy else "UNAVAILABLE"
    code = 200 if healthy else 503
    return HttpResponse(body, content_type="text/plain", status=code, headers=_NO_STORE)


def _contract_results(request, query):
    company = getattr(request, "active_company", None)
    if company is None:
        raise PermissionDenied("No active company set")

    canonical = normalize_contract_number(query) or query
    candidates = {query, canonical}
    match_filter = Q()
    for candidate in candidates:
        match_filter |= Q(contract_number__icontains=candidate)

    return (
        Contract.objects.filter(company=company)
        .filter(match_filter)
        .annotate(
            match_quality=Case(
                *[
                    When(contract_number__iexact=candidate, then=Value(0))
                    for candidate in candidates
                ],
                *[
                    When(contract_number__istartswith=candidate, then=Value(1))
                    for candidate in candidates
                ],
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .select_related("status")
        .order_by("match_quality", "contract_number", "pk")
    )


def _supplier_results(query):
    cage_token = query.upper() if _CAGE_RE.fullmatch(query) else ""
    cage_supplier_ids = []
    if cage_token:
        cage_supplier_ids = [
            supplier.pk for supplier in _suppliers_matching_cage(cage_token)
        ]

    match_filter = (
        Q(name__icontains=query)
        | Q(aliases__name__icontains=query)
        | Q(cage_code__icontains=query)
    )
    if cage_supplier_ids:
        match_filter |= Q(pk__in=cage_supplier_ids)

    quality = Case(
        When(name__iexact=query, then=Value(0)),
        When(aliases__name__iexact=query, then=Value(0)),
        When(cage_code__iexact=query, then=Value(0)),
        When(pk__in=cage_supplier_ids, then=Value(0)),
        When(name__istartswith=query, then=Value(1)),
        When(aliases__name__istartswith=query, then=Value(1)),
        When(cage_code__istartswith=query, then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )
    return (
        Supplier.objects.filter(archived=False)
        .filter(match_filter)
        .annotate(match_quality=Min(quality))
        .order_by("match_quality", "name", "pk")
    )


def _nsn_results(query):
    variants = nsn_query_variants(query)
    normalized = normalize_nsn(query)

    match_filter = Q(part_number__icontains=query)
    for variant in variants:
        match_filter |= Q(nsn_code__icontains=variant)
        normalized_variant = normalize_nsn(variant)
        if normalized_variant:
            match_filter |= Q(nsn_normalized__icontains=normalized_variant)
    if len(normalized) == 9 and normalized.isdigit():
        match_filter |= Q(nsn_normalized__endswith=normalized)

    exact_conditions = [
        When(nsn_code__iexact=variant, then=Value(0)) for variant in variants
    ]
    if normalized:
        exact_conditions.append(
            When(nsn_normalized__iexact=normalized, then=Value(0))
        )
    exact_conditions.append(When(part_number__iexact=query, then=Value(0)))

    starts_conditions = [
        When(nsn_code__istartswith=variant, then=Value(1)) for variant in variants
    ]
    if normalized:
        starts_conditions.append(
            When(nsn_normalized__istartswith=normalized, then=Value(1))
        )
    starts_conditions.append(When(part_number__istartswith=query, then=Value(1)))

    return (
        Nsn.objects.filter(match_filter)
        .annotate(
            match_quality=Case(
                *exact_conditions,
                *starts_conditions,
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("match_quality", "nsn_code", "pk")
    )


def _solicitation_results(query):
    quality = Case(
        When(solicitation_number__iexact=query, then=Value(0)),
        When(lines__nomenclature__iexact=query, then=Value(0)),
        When(solicitation_number__istartswith=query, then=Value(1)),
        When(lines__nomenclature__istartswith=query, then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )
    return (
        Solicitation.objects.filter(
            Q(solicitation_number__icontains=query)
            | Q(lines__nomenclature__icontains=query)
        )
        .annotate(match_quality=Min(quality))
        .select_related("import_batch")
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=SolicitationLine.objects.order_by("line_number", "pk"),
                to_attr="search_lines",
            )
        )
        .order_by("match_quality", "solicitation_number")
    )


def _materialize_category(queryset, selected_category, category, page_number):
    total = queryset.count()
    if selected_category == category:
        paginator = Paginator(queryset, _SEARCH_RESULT_LIMIT)
        page = paginator.get_page(page_number)
        results = list(page.object_list)
        return total, results, page
    return total, list(queryset[:_SEARCH_RESULT_LIMIT]), None


@login_required
@require_GET
def global_search(request):
    query = (request.GET.get("q") or "").strip()[:200]
    if not query:
        return redirect("index")

    valid_categories = {"contracts", "suppliers", "nsns", "solicitations"}
    selected_category = (request.GET.get("category") or "").strip().lower()
    if selected_category not in valid_categories:
        selected_category = ""
    page_number = request.GET.get("page", 1)

    contracts_total, contracts, contracts_page = _materialize_category(
        _contract_results(request, query),
        selected_category,
        "contracts",
        page_number,
    )
    suppliers_total, suppliers, suppliers_page = _materialize_category(
        _supplier_results(query),
        selected_category,
        "suppliers",
        page_number,
    )
    nsns_total, nsns, nsns_page = _materialize_category(
        _nsn_results(query),
        selected_category,
        "nsns",
        page_number,
    )
    solicitations_total, solicitations, solicitations_page = _materialize_category(
        _solicitation_results(query),
        selected_category,
        "solicitations",
        page_number,
    )

    return render(
        request,
        "core/global_search_results.html",
        {
            "query": query,
            "selected_category": selected_category,
            "contracts": contracts,
            "contracts_total": contracts_total,
            "contracts_page": contracts_page,
            "suppliers": suppliers,
            "suppliers_total": suppliers_total,
            "suppliers_page": suppliers_page,
            "nsns": nsns,
            "nsns_total": nsns_total,
            "nsns_page": nsns_page,
            "solicitations": solicitations,
            "solicitations_total": solicitations_total,
            "solicitations_page": solicitations_page,
        },
    )


from decimal import Decimal, InvalidOperation
from django.views.decorators.http import require_POST
from django.utils.timezone import now
from core.models import APIBudget

@login_required
@require_POST
def sync_api_budget(request):
    if not request.user.is_superuser:
        return JsonResponse({"success": False, "error": "Superuser permission required."}, status=403)
    
    new_balance_str = request.POST.get("new_balance")
    if new_balance_str is None:
        return JsonResponse({"success": False, "error": "Missing new_balance parameter."}, status=400)
    
    try:
        new_balance = Decimal(new_balance_str)
        if new_balance < 0:
            raise ValueError("Balance must be a positive number.")
    except (InvalidOperation, ValueError):
        return JsonResponse({"success": False, "error": "Please enter a valid positive balance."}, status=400)
        
    budget = APIBudget.get()
    budget.balance_usd = new_balance
    budget.last_sync_amount = new_balance
    budget.last_sync_at = now()
    budget.save(update_fields=['balance_usd', 'last_sync_amount', 'last_sync_at', 'updated_at'])
    
    return JsonResponse({"success": True, "new_balance": str(budget.balance_usd)})

