import re
from dataclasses import dataclass
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Prefetch, Q, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET

from core.health import run_readiness_check
from contracts.models import (
    Clin,
    Contract,
    IdiqContract,
    IdiqContractDetails,
    PurchaseOrder,
)
from contracts.services.contract_number import normalize_contract_number
from products.models import Nsn
from products.nsn_utils import normalize_nsn, nsn_query_variants
from products.views import _suppliers_matching_cage
from sales.models import Solicitation, SolicitationLine, SupplierMatch, SupplierRFQ
from suppliers.models import Supplier

_NO_STORE = {"Cache-Control": "no-store"}
_SEARCH_RESULT_LIMIT = 10
_CAGE_RE = re.compile(r"^[A-Za-z0-9]{5}$")
_CONTRACT_SHAPE_RE = re.compile(
    r"^[A-Za-z0-9]{6}[- ]?\d{2}[- ]?[A-Za-z][- ]?[A-Za-z0-9]{2,6}$"
)
# Shorter terms are matched exactly; `LIKE '%ab%'` scans are not worth running.
_MIN_CONTAINS_LEN = 3
# Smallest digit run worth probing the DIBBS NSN/NIIN columns with.
_MIN_NSN_DIGITS = 7
# Per-query cap on collected primary keys, kept well under the SQL Server
# 2,100 parameter limit once several id sets are merged into one `pk__in`.
_SOURCE_ID_LIMIT = 500
_CATEGORY_ID_LIMIT = 1000
_SEARCH_CATEGORIES = ("contracts", "idiqs", "suppliers", "nsns", "solicitations")
_SEARCH_GROUP_LABELS = {
    "contracts": "Contracts",
    "idiqs": "IDIQs",
    "suppliers": "Suppliers",
    "nsns": "NSN",
    "solicitations": "Solicitations",
}


@dataclass(frozen=True)
class _SearchTerms:
    query: str
    contract_candidates: tuple[str, ...]
    nsn_variants: tuple[str, ...]
    normalized_nsn: str
    cage_supplier_ids: tuple[int, ...]
    wants_text_scan: bool
    is_nsn_shaped: bool


@dataclass(frozen=True)
class _MatchedIds:
    """Primary keys matched directly on each model's own columns."""

    contracts: set
    idiqs: set
    suppliers: set
    nsns: set
    solicitations: set


def _wants_text_scan(query):
    """Only word-shaped terms are worth scanning free-text columns for.

    Contract numbers and NSNs never appear in item nomenclature, and that
    column is the largest table in the search (one row per solicitation line).
    """
    if _CONTRACT_SHAPE_RE.fullmatch(query):
        return False
    digits = sum(character.isdigit() for character in query)
    return digits * 2 < len(query)


def _is_nsn_shaped(normalized_nsn):
    """DIBBS NSN and NIIN columns only ever hold digit codes (9 or 13 long)."""
    return len(normalized_nsn) >= _MIN_NSN_DIGITS and normalized_nsn.isdigit()


def _build_search_terms(query):
    canonical_contract = normalize_contract_number(query) or query
    contract_candidates = tuple(dict.fromkeys((query, canonical_contract)))
    nsn_variants = tuple(nsn_query_variants(query))
    normalized_nsn = normalize_nsn(query)
    cage_supplier_ids = ()
    if _CAGE_RE.fullmatch(query):
        cage_supplier_ids = tuple(
            supplier.pk for supplier in _suppliers_matching_cage(query.upper())
        )
    return _SearchTerms(
        query=query,
        contract_candidates=contract_candidates,
        nsn_variants=nsn_variants,
        normalized_nsn=normalized_nsn,
        cage_supplier_ids=cage_supplier_ids,
        wants_text_scan=_wants_text_scan(query),
        is_nsn_shaped=_is_nsn_shaped(normalized_nsn),
    )


# Lookups below are deliberately case-sensitive Django lookups: SQL Server runs
# a `CI_AS` collation and SQLite's LIKE is ASCII case-insensitive, so both stay
# case-insensitive without the `UPPER()` wrapper that `icontains` adds — and
# `UPPER()` makes every indexed column non-sargable.
def _contains_q(field, value):
    if len(value) < _MIN_CONTAINS_LEN:
        return Q(**{f"{field}__exact": value})
    return Q(**{f"{field}__contains": value})


def _starts_q(field, value):
    """Prefix match on an indexed column so SQL Server can seek it."""
    if len(value) < _MIN_CONTAINS_LEN:
        return Q(**{f"{field}__exact": value})
    return Q(**{f"{field}__startswith": value})


def _ids(queryset, field="pk"):
    return set(queryset.values_list(field, flat=True)[:_SOURCE_ID_LIMIT])


def _quality_case(pairs):
    """Rank rows exact, then starts-with, then contains, then related-only."""
    whens = [When(**{f"{field}__exact": value}, then=Value(0)) for field, value in pairs]
    whens += [
        When(**{f"{field}__startswith": value}, then=Value(1))
        for field, value in pairs
    ]
    whens += [
        When(**{f"{field}__contains": value}, then=Value(2))
        for field, value in pairs
        if len(value) >= _MIN_CONTAINS_LEN
    ]
    return Case(*whens, default=Value(3), output_field=IntegerField())


def _contract_number_filter(terms):
    number_filter = Q()
    for candidate in terms.contract_candidates:
        number_filter |= _contains_q("contract_number", candidate)
    return number_filter


def _nsn_column_filter(terms):
    nsn_filter = _contains_q("part_number", terms.query)
    for variant in terms.nsn_variants:
        nsn_filter |= _contains_q("nsn_code", variant)
        normalized_variant = normalize_nsn(variant)
        if normalized_variant:
            nsn_filter |= _contains_q("nsn_normalized", normalized_variant)
    if len(terms.normalized_nsn) == 9 and terms.normalized_nsn.isdigit():
        nsn_filter |= Q(nsn_normalized__endswith=terms.normalized_nsn)
    return nsn_filter


def _indexed_line_filter(terms):
    """NSN/NIIN prefix matches — these can seek `dibbs_solicitation_line.nsn`."""
    line_filter = Q()
    if not terms.is_nsn_shaped:
        return line_filter
    for variant in terms.nsn_variants:
        line_filter |= _starts_q("nsn", variant)
        normalized_variant = normalize_nsn(variant)
        if normalized_variant:
            line_filter |= _starts_q("nsn", normalized_variant)
    if len(terms.normalized_nsn) == 9:
        line_filter |= Q(niin__exact=terms.normalized_nsn)
    return line_filter


def _nomenclature_line_filter(terms):
    """Item-name contains scan. Unindexed; never run on the first paint."""
    if not terms.wants_text_scan:
        return Q()
    return _contains_q("nomenclature", terms.query)


def _solicitation_line_filter(terms):
    """Indexed NSN/NIIN plus the optional nomenclature scan."""
    return _indexed_line_filter(terms) | _nomenclature_line_filter(terms)


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


def _direct_matches(terms, company, *, include_indexed_lines=True):
    """Match each model on its own indexed columns — no joins, no aggregation."""
    number_filter = _contract_number_filter(terms)
    po_filter = _contains_q("po_number", terms.query) | _contains_q(
        "prime_po_number", terms.query
    )
    contract_ids = _ids(
        Contract.objects.filter(company=company).filter(number_filter | po_filter)
    )
    # Clin.clin_po_num is the UI Sub PO # and stays in sync with Contract.po_number.
    # Collect ids separately so this stays a pk lookup, not a join on the group query.
    contract_ids |= _ids(
        Clin.objects.filter(company=company).filter(
            _contains_q("clin_po_num", terms.query)
        ),
        "contract_id",
    )
    contract_ids |= _ids(
        PurchaseOrder.objects.filter(company=company).filter(
            _contains_q("po_number", terms.query)
        ),
        "contract_id",
    )
    contract_ids.discard(None)

    suppliers = _ids(
        Supplier.objects.filter(archived=False).filter(
            _contains_q("name", terms.query) | _contains_q("cage_code", terms.query)
        )
    )
    suppliers |= _ids(
        Supplier.objects.filter(archived=False).filter(
            _contains_q("aliases__name", terms.query)
        )
    )
    suppliers.update(terms.cage_supplier_ids)

    # Prefix match: `solicitation_number` is unique-indexed on a table with
    # hundreds of thousands of rows, so a contains scan is not affordable.
    solicitations = _ids(
        Solicitation.objects.filter(_starts_q("solicitation_number", terms.query))
    )
    if include_indexed_lines:
        indexed_lines = _indexed_line_filter(terms)
        if indexed_lines:
            solicitations |= _ids(
                SolicitationLine.objects.filter(indexed_lines), "solicitation_id"
            )

    return _MatchedIds(
        contracts=contract_ids,
        idiqs=_ids(
            IdiqContract.objects.filter(company=company).filter(number_filter)
        ),
        suppliers=suppliers,
        nsns=_ids(Nsn.objects.filter(_nsn_column_filter(terms))),
        solicitations=solicitations,
    )


def _clin_ids(company, row_filter, field):
    return _ids(Clin.objects.filter(company=company).filter(row_filter), field)


def _idiq_detail_ids(company, row_filter, field):
    return _ids(
        IdiqContractDetails.objects.filter(idiq_contract__company=company).filter(
            row_filter
        ),
        field,
    )


def _related_contract_ids(direct, company):
    ids = set()
    clin_filter = Q()
    if direct.suppliers:
        clin_filter |= Q(supplier_id__in=direct.suppliers)
    if direct.nsns:
        clin_filter |= Q(nsn_id__in=direct.nsns)
    if clin_filter:
        ids |= _clin_ids(company, clin_filter, "contract_id")
    if direct.idiqs:
        ids |= _ids(
            Contract.objects.filter(
                company=company, idiq_contract_id__in=direct.idiqs
            )
        )
    ids.discard(None)
    return ids


def _related_idiq_ids(direct, company):
    detail_filter = Q()
    if direct.suppliers:
        detail_filter |= Q(supplier_id__in=direct.suppliers)
    if direct.nsns:
        detail_filter |= Q(nsn_id__in=direct.nsns)
    if not detail_filter:
        return set()
    return _idiq_detail_ids(company, detail_filter, "idiq_contract_id")


def _related_supplier_ids(direct, company):
    ids = set()
    if direct.nsns:
        ids |= _clin_ids(company, Q(nsn_id__in=direct.nsns), "supplier_id")
    if direct.idiqs:
        ids |= _idiq_detail_ids(
            company, Q(idiq_contract_id__in=direct.idiqs), "supplier_id"
        )
    if direct.solicitations:
        line_filter = Q(line__solicitation_id__in=direct.solicitations)
        ids |= _ids(SupplierMatch.objects.filter(line_filter), "supplier_id")
        ids |= _ids(SupplierRFQ.objects.filter(line_filter), "supplier_id")
    ids.discard(None)
    return ids


def _related_nsn_ids(direct, company):
    ids = set()
    if direct.suppliers:
        ids |= _clin_ids(company, Q(supplier_id__in=direct.suppliers), "nsn_id")
    if direct.idiqs:
        ids |= _idiq_detail_ids(
            company, Q(idiq_contract_id__in=direct.idiqs), "nsn_id"
        )
    ids.discard(None)
    return ids


def _related_solicitation_ids(direct):
    if not direct.suppliers:
        return set()
    supplier_filter = Q(supplier_id__in=direct.suppliers)
    ids = _ids(
        SupplierMatch.objects.filter(supplier_filter), "line__solicitation_id"
    )
    ids |= _ids(SupplierRFQ.objects.filter(supplier_filter), "line__solicitation_id")
    ids.discard(None)
    return ids


def _category_ids(direct_ids, related_ids):
    """Direct matches first so truncation never drops them."""
    ordered = list(direct_ids) + [pk for pk in related_ids if pk not in direct_ids]
    return ordered[:_CATEGORY_ID_LIMIT]


def _nomenclature_solicitation_ids(terms):
    nomenclature_filter = _nomenclature_line_filter(terms)
    if not nomenclature_filter:
        return set()
    return _ids(
        SolicitationLine.objects.filter(nomenclature_filter), "solicitation_id"
    )


def _related_matches(direct, terms, company):
    """One-hop ids plus the unindexed nomenclature scan.

    Nomenclature hits are folded into `solicitations` before the supplier hop
    so a word search still surfaces matched/RFQ suppliers for those lines.
    """
    nomenclature = _nomenclature_solicitation_ids(terms)
    hop_solicitations = direct.solicitations | nomenclature
    hopped = _MatchedIds(
        contracts=direct.contracts,
        idiqs=direct.idiqs,
        suppliers=direct.suppliers,
        nsns=direct.nsns,
        solicitations=hop_solicitations,
    )
    return _MatchedIds(
        contracts=_related_contract_ids(hopped, company),
        idiqs=_related_idiq_ids(hopped, company),
        suppliers=_related_supplier_ids(hopped, company),
        nsns=_related_nsn_ids(hopped, company),
        solicitations=_related_solicitation_ids(hopped) | nomenclature,
    )


def _category_id_map(direct, related, mode):
    """Pick the pk set each group queryset should load for this request mode."""
    id_map = {}
    for category in _SEARCH_CATEGORIES:
        direct_ids = getattr(direct, category)
        related_ids = getattr(related, category)
        if mode == "fast":
            id_map[category] = list(direct_ids)[:_CATEGORY_ID_LIMIT]
        elif mode == "deep":
            id_map[category] = _category_ids(set(), related_ids - direct_ids)
        else:
            id_map[category] = _category_ids(direct_ids, related_ids)
    return id_map


def _search_querysets(request, terms, mode="full"):
    """Build one flat, index-friendly queryset per result group.

    `mode`:
    - ``fast`` — indexed columns only (first paint)
    - ``deep`` — related hops + nomenclature, excluding already-shown directs
    - ``full`` — union used by category pagination and no-JS complete search

    Relationships are resolved as primary-key lookups instead of OR'd joins:
    a single `pk__in` filter keeps every group query free of the outer-join
    fan-out and `GROUP BY` that made the previous version unusable.
    """
    if mode not in {"fast", "deep", "full"}:
        raise ValueError(f"Unknown search mode {mode!r}")

    company = getattr(request, "active_company", None)
    if company is None:
        raise PermissionDenied("No active company set")

    direct = _direct_matches(terms, company)
    related = _MatchedIds(
        contracts=set(),
        idiqs=set(),
        suppliers=set(),
        nsns=set(),
        solicitations=set(),
    )
    if mode != "fast":
        related = _related_matches(direct, terms, company)

    number_pairs = [
        ("contract_number", candidate) for candidate in terms.contract_candidates
    ]
    contract_pairs = number_pairs + [
        ("po_number", terms.query),
        ("prime_po_number", terms.query),
    ]
    nsn_pairs = [("nsn_code", variant) for variant in terms.nsn_variants]
    if terms.normalized_nsn:
        nsn_pairs.append(("nsn_normalized", terms.normalized_nsn))
    nsn_pairs.append(("part_number", terms.query))
    id_map = _category_id_map(direct, related, mode)

    def _or_none(model, pks):
        if not pks:
            return model.objects.none()
        return model.objects.filter(pk__in=pks)

    contracts = (
        _or_none(Contract, id_map["contracts"])
        .annotate(match_quality=_quality_case(contract_pairs))
        .select_related("status", "purchase_order")
        .order_by("match_quality", "contract_number", "pk")
    )
    idiqs = (
        _or_none(IdiqContract, id_map["idiqs"])
        .annotate(match_quality=_quality_case(number_pairs))
        .select_related("buyer")
        .order_by("match_quality", "contract_number", "pk")
    )
    suppliers = (
        _or_none(Supplier, id_map["suppliers"])
        .annotate(
            match_quality=_quality_case(
                [("name", terms.query), ("cage_code", terms.query)]
            )
        )
        .order_by("match_quality", "name", "pk")
    )
    nsns = (
        _or_none(Nsn, id_map["nsns"])
        .annotate(match_quality=_quality_case(nsn_pairs))
        .order_by("match_quality", "nsn_code", "pk")
    )
    solicitations = (
        _or_none(Solicitation, id_map["solicitations"])
        .annotate(
            match_quality=_quality_case([("solicitation_number", terms.query)])
        )
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
    return {
        "contracts": contracts,
        "idiqs": idiqs,
        "suppliers": suppliers,
        "nsns": nsns,
        "solicitations": solicitations,
    }


def _materialize_category(queryset, selected_category, category, page_number):
    if queryset.query.is_empty():
        return 0, [], None
    total = queryset.count()
    if selected_category == category:
        paginator = Paginator(queryset, _SEARCH_RESULT_LIMIT)
        page = paginator.get_page(page_number)
        results = list(page.object_list)
        return total, results, page
    return total, list(queryset[:_SEARCH_RESULT_LIMIT]), None


def _search_page_context(querysets, query, selected_category, page_number):
    context = {"query": query, "selected_category": selected_category}
    for category, queryset in querysets.items():
        total, results, page = _materialize_category(
            queryset, selected_category, category, page_number
        )
        context[category] = results
        context[f"{category}_total"] = total
        context[f"{category}_page"] = page
    return context


@login_required
@require_GET
def global_search(request):
    query = (request.GET.get("q") or "").strip()[:200]
    if not query:
        return redirect("index")
    terms = _build_search_terms(query)
    selected_category = (request.GET.get("category") or "").strip().lower()
    if selected_category not in _SEARCH_CATEGORIES:
        selected_category = ""
    complete = (request.GET.get("complete") or "") == "1"
    page_number = request.GET.get("page", 1)
    load_related = not selected_category and not complete
    mode = "fast" if load_related else "full"
    context = _search_page_context(
        _search_querysets(request, terms, mode=mode),
        query,
        selected_category,
        page_number,
    )
    context["load_related"] = load_related
    context["related_url"] = (
        f"{reverse('core:global_search_related')}?{urlencode({'q': query})}"
    )
    context["complete_url"] = (
        f"{reverse('core:global_search')}?{urlencode({'q': query, 'complete': '1'})}"
    )
    return render(request, "core/global_search_results.html", context)


@login_required
@require_GET
def global_search_related(request):
    query = (request.GET.get("q") or "").strip()[:200]
    if not query:
        return JsonResponse({"groups": []}, headers=_NO_STORE)

    terms = _build_search_terms(query)
    fast = _search_page_context(
        _search_querysets(request, terms, mode="fast"), query, "", 1
    )
    deep = _search_page_context(
        _search_querysets(request, terms, mode="deep"), query, "", 1
    )
    groups = []
    for category in _SEARCH_CATEGORIES:
        rows = deep[category]
        if not rows:
            continue
        total = fast[f"{category}_total"] + deep[f"{category}_total"]
        html = render_to_string(
            f"core/partials/search_{category}_rows.html",
            {category: rows, "query": query},
        )
        view_all = ""
        if total > _SEARCH_RESULT_LIMIT:
            view_all = (
                f"{reverse('core:global_search')}?"
                f"{urlencode({'q': query, 'category': category})}"
            )
        groups.append(
            {
                "category": category,
                "label": _SEARCH_GROUP_LABELS[category],
                "html": html,
                "total": total,
                "added": len(rows),
                "view_all_url": view_all,
            }
        )
    return JsonResponse({"groups": groups}, headers=_NO_STORE)


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

