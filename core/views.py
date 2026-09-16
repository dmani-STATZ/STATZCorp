import re
from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Min, Prefetch, Q, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from core.health import run_readiness_check
from contracts.models import Contract, IdiqContract
from contracts.services.contract_number import normalize_contract_number
from products.models import Nsn
from products.nsn_utils import normalize_nsn, nsn_query_variants
from products.views import _suppliers_matching_cage
from sales.models import Solicitation, SolicitationLine
from suppliers.models import Supplier

_NO_STORE = {"Cache-Control": "no-store"}
_SEARCH_RESULT_LIMIT = 10
_CAGE_RE = re.compile(r"^[A-Za-z0-9]{5}$")


@dataclass(frozen=True)
class _SearchTerms:
    query: str
    contract_candidates: tuple[str, ...]
    nsn_variants: tuple[str, ...]
    normalized_nsn: str
    cage_supplier_ids: tuple[int, ...]


def _build_search_terms(query):
    canonical_contract = normalize_contract_number(query) or query
    contract_candidates = tuple(dict.fromkeys((query, canonical_contract)))
    nsn_variants = tuple(nsn_query_variants(query))
    cage_supplier_ids = ()
    if _CAGE_RE.fullmatch(query):
        cage_supplier_ids = tuple(
            supplier.pk for supplier in _suppliers_matching_cage(query.upper())
        )
    return _SearchTerms(
        query=query,
        contract_candidates=contract_candidates,
        nsn_variants=nsn_variants,
        normalized_nsn=normalize_nsn(query),
        cage_supplier_ids=cage_supplier_ids,
    )


def _supplier_match_filter(terms, prefix=""):
    query = terms.query
    match_filter = (
        Q(**{f"{prefix}name__icontains": query})
        | Q(**{f"{prefix}aliases__name__icontains": query})
        | Q(**{f"{prefix}cage_code__icontains": query})
    )
    if terms.cage_supplier_ids:
        match_filter |= Q(**{f"{prefix}pk__in": terms.cage_supplier_ids})
    return match_filter


def _nsn_match_filter(terms, prefix=""):
    match_filter = Q(**{f"{prefix}part_number__icontains": terms.query})
    for variant in terms.nsn_variants:
        match_filter |= Q(**{f"{prefix}nsn_code__icontains": variant})
        normalized_variant = normalize_nsn(variant)
        if normalized_variant:
            match_filter |= Q(
                **{f"{prefix}nsn_normalized__icontains": normalized_variant}
            )
    if len(terms.normalized_nsn) == 9 and terms.normalized_nsn.isdigit():
        match_filter |= Q(
            **{f"{prefix}nsn_normalized__endswith": terms.normalized_nsn}
        )
    return match_filter


def _idiq_number_filter(terms, prefix=""):
    match_filter = Q()
    for candidate in terms.contract_candidates:
        match_filter |= Q(**{f"{prefix}contract_number__icontains": candidate})
    return match_filter


def _solicitation_line_nsn_filter(terms, prefix="lines__"):
    match_filter = Q()
    for variant in terms.nsn_variants:
        match_filter |= Q(**{f"{prefix}nsn__icontains": variant})
        normalized_variant = normalize_nsn(variant)
        if normalized_variant:
            match_filter |= Q(
                **{f"{prefix}nsn__icontains": normalized_variant}
            )
    if len(terms.normalized_nsn) == 9 and terms.normalized_nsn.isdigit():
        match_filter |= Q(
            **{f"{prefix}niin__iexact": terms.normalized_nsn}
        )
    return match_filter


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


def _contract_results(request, terms):
    company = getattr(request, "active_company", None)
    if company is None:
        raise PermissionDenied("No active company set")

    direct_filter = Q()
    for candidate in terms.contract_candidates:
        direct_filter |= Q(contract_number__icontains=candidate)
    related_filter = (
        _supplier_match_filter(terms, "clin__supplier__")
        | _nsn_match_filter(terms, "clin__nsn__")
        | (
            _idiq_number_filter(terms, "idiq_contract__")
            & Q(idiq_contract__company=company)
        )
    )

    return (
        Contract.objects.filter(company=company)
        .filter(direct_filter | related_filter)
        .annotate(
            match_quality=Min(
                Case(
                    *[
                        When(contract_number__iexact=candidate, then=Value(0))
                        for candidate in terms.contract_candidates
                    ],
                    *[
                        When(contract_number__istartswith=candidate, then=Value(1))
                        for candidate in terms.contract_candidates
                    ],
                    When(direct_filter, then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            )
        )
        .select_related("status")
        .order_by("match_quality", "contract_number", "pk")
    )


def _supplier_results(terms, company):
    query = terms.query
    direct_filter = _supplier_match_filter(terms)
    related_filter = (
        (_nsn_match_filter(terms, "clin__nsn__") & Q(clin__company=company))
        | _solicitation_line_nsn_filter(terms, "dibbs_matches__line__")
        | _solicitation_line_nsn_filter(terms, "dibbs_rfqs__line__")
        | Q(
            dibbs_matches__line__solicitation__solicitation_number__icontains=query
        )
        | Q(dibbs_rfqs__line__solicitation__solicitation_number__icontains=query)
        | (
            _idiq_number_filter(
                terms, "idiqcontractdetails__idiq_contract__"
            )
            & Q(idiqcontractdetails__idiq_contract__company=company)
        )
    )

    quality = Case(
        When(name__iexact=query, then=Value(0)),
        When(aliases__name__iexact=query, then=Value(0)),
        When(cage_code__iexact=query, then=Value(0)),
        When(pk__in=terms.cage_supplier_ids, then=Value(0)),
        When(name__istartswith=query, then=Value(1)),
        When(aliases__name__istartswith=query, then=Value(1)),
        When(cage_code__istartswith=query, then=Value(1)),
        When(direct_filter, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )
    return (
        Supplier.objects.filter(archived=False)
        .filter(direct_filter | related_filter)
        .annotate(match_quality=Min(quality))
        .order_by("match_quality", "name", "pk")
    )


def _nsn_results(terms, company):
    query = terms.query
    direct_filter = _nsn_match_filter(terms)
    related_filter = (
        _supplier_match_filter(terms, "clin__supplier__")
        & Q(clin__company=company)
    ) | (
        _idiq_number_filter(terms, "idiqcontractdetails__idiq_contract__")
        & Q(idiqcontractdetails__idiq_contract__company=company)
    )

    exact_conditions = [
        When(nsn_code__iexact=variant, then=Value(0))
        for variant in terms.nsn_variants
    ]
    if terms.normalized_nsn:
        exact_conditions.append(
            When(nsn_normalized__iexact=terms.normalized_nsn, then=Value(0))
        )
    exact_conditions.append(When(part_number__iexact=query, then=Value(0)))

    starts_conditions = [
        When(nsn_code__istartswith=variant, then=Value(1))
        for variant in terms.nsn_variants
    ]
    if terms.normalized_nsn:
        starts_conditions.append(
            When(nsn_normalized__istartswith=terms.normalized_nsn, then=Value(1))
        )
    starts_conditions.append(When(part_number__istartswith=query, then=Value(1)))

    return (
        Nsn.objects.filter(direct_filter | related_filter)
        .annotate(
            match_quality=Min(
                Case(
                    *exact_conditions,
                    *starts_conditions,
                    When(direct_filter, then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            )
        )
        .order_by("match_quality", "nsn_code", "pk")
    )


def _solicitation_results(terms):
    query = terms.query
    direct_filter = (
        Q(solicitation_number__icontains=query)
        | Q(lines__nomenclature__icontains=query)
        | _solicitation_line_nsn_filter(terms)
    )
    related_filter = _supplier_match_filter(
        terms, "lines__supplier_matches__supplier__"
    ) | _supplier_match_filter(terms, "lines__rfqs__supplier__")
    quality = Case(
        When(solicitation_number__iexact=query, then=Value(0)),
        When(lines__nomenclature__iexact=query, then=Value(0)),
        When(lines__nsn__iexact=terms.normalized_nsn, then=Value(0)),
        When(lines__niin__iexact=terms.normalized_nsn, then=Value(0)),
        When(solicitation_number__istartswith=query, then=Value(1)),
        When(lines__nomenclature__istartswith=query, then=Value(1)),
        When(direct_filter, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )
    return (
        Solicitation.objects.filter(direct_filter | related_filter)
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


def _idiq_results(request, terms):
    company = getattr(request, "active_company", None)
    if company is None:
        raise PermissionDenied("No active company set")

    direct_filter = _idiq_number_filter(terms)
    related_filter = _supplier_match_filter(
        terms, "idiqcontractdetails__supplier__"
    ) | _nsn_match_filter(terms, "idiqcontractdetails__nsn__")
    return (
        IdiqContract.objects.filter(company=company)
        .filter(direct_filter | related_filter)
        .annotate(
            match_quality=Min(
                Case(
                    *[
                        When(contract_number__iexact=candidate, then=Value(0))
                        for candidate in terms.contract_candidates
                    ],
                    *[
                        When(contract_number__istartswith=candidate, then=Value(1))
                        for candidate in terms.contract_candidates
                    ],
                    When(direct_filter, then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            )
        )
        .select_related("buyer")
        .order_by("match_quality", "contract_number", "pk")
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
    terms = _build_search_terms(query)
    company = getattr(request, "active_company", None)
    if company is None:
        raise PermissionDenied("No active company set")

    valid_categories = {"contracts", "idiqs", "suppliers", "nsns", "solicitations"}
    selected_category = (request.GET.get("category") or "").strip().lower()
    if selected_category not in valid_categories:
        selected_category = ""
    page_number = request.GET.get("page", 1)

    contracts_total, contracts, contracts_page = _materialize_category(
        _contract_results(request, terms),
        selected_category,
        "contracts",
        page_number,
    )
    idiqs_total, idiqs, idiqs_page = _materialize_category(
        _idiq_results(request, terms),
        selected_category,
        "idiqs",
        page_number,
    )
    suppliers_total, suppliers, suppliers_page = _materialize_category(
        _supplier_results(terms, company),
        selected_category,
        "suppliers",
        page_number,
    )
    nsns_total, nsns, nsns_page = _materialize_category(
        _nsn_results(terms, company),
        selected_category,
        "nsns",
        page_number,
    )
    solicitations_total, solicitations, solicitations_page = _materialize_category(
        _solicitation_results(terms),
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
            "idiqs": idiqs,
            "idiqs_total": idiqs_total,
            "idiqs_page": idiqs_page,
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

