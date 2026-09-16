# Core Context

## Purpose
`core` owns cross-cutting infrastructure that does not belong to a domain app: scheduled-task orchestration, API budget tracking, health endpoints, and the authenticated global portal search.

## Global portal search
- URL: `/core/search/` (`core:global_search`), GET only. Related records load from `/core/search/related/` (`core:global_search_related`).
- Empty `q` redirects to `/home/` (`index`).
- The initial page is the **fast path**: indexed columns only (contract/IDIQ number, supplier name/CAGE/alias, NSN/NIIN/part number, solicitation-number prefix, and NSN-shaped solicitation lines). It materializes at most 10 rows per group.
- JavaScript then fetches `core:global_search_related` and appends one-hop related rows plus nomenclature matches. `?category=` pagination and `?complete=1` run the **full** union in one request (no second fetch).
- Match order is exact, starts-with, then contains.
- Contract and IDIQ searches always filter `company=request.active_company` and reuse `contracts.services.contract_number.normalize_contract_number`.
- Supplier searches are global, exclude `archived=True`, include aliases, and reuse `products.views._suppliers_matching_cage` for CAGE-shaped tokens.
- NSN searches are global and must use `products.nsn_utils.nsn_query_variants`; NSN, normalized NSN/NIIN, and part number are searched.
- Solicitation searches are global across `solicitation_number` and `SolicitationLine.nomenclature`.
- Results expand one relationship hop: supplier and NSN matches find active-company contracts through `Clin`; supplier matches can surface their CLIN NSNs and matched/RFQ solicitations; NSN matches can surface active-company CLIN suppliers plus suppliers associated through solicitation matches/RFQs; solicitation lines match NSN/NIIN directly. IDIQ number matches also return that company's delivery-order `Contract` rows plus `IdiqContractDetails` suppliers and NSNs. Supplier/NSN terms can surface the parent IDIQ through those details.
- Any relationship traversing `Clin` must include `Clin.company=request.active_company`. IDIQ detail hops must include `IdiqContract.company=request.active_company`. This prevents a global Supplier or Nsn result from exposing another company's contract associations.
- `SupplierNSNCapability` is not a search source.
- Querysets are materialized independently before the next model query to remain safe with SQL Server when MARS is disabled.

## Global portal search query strategy
The search runs in two passes, and the shape is load bearing: an earlier version OR'd every relationship into one filter per group and took over a minute in production.

The first HTML response is `mode="fast"` (indexed columns only). Related hops and the nomenclature scan run as `mode="deep"` on `/core/search/related/` so a contract/NSN/IDIQ lookup is not blocked by DIBBS line scans.

1. `_direct_matches()` matches each model on its **own columns only** and collects primary keys (capped at `_SOURCE_ID_LIMIT`). Indexed solicitation-line NSN/NIIN prefix matches are included here; nomenclature is not.
2. `_related_*_ids()` resolves relationships as `FK id__in <ids>` lookups against `Clin`, `IdiqContractDetails`, `SupplierMatch`, and `SupplierRFQ`. `_related_matches()` also runs the nomenclature contains scan.
3. `_search_querysets(mode=...)` returns one `pk__in` queryset per group (capped at `_CATEGORY_ID_LIMIT`, direct matches first), ordered by a `Case` over own columns. `mode="deep"` excludes ids already returned by the fast path so the JS append is disjoint.

Rules that keep it fast:
- **No joins or aggregates in the group querysets.** OR'd joins produce an outer-join fan-out that needs `GROUP BY`/`Min()` to dedupe, which is what made the page unusable.
- **Never use `icontains`/`istartswith`/`iexact` here.** SQL Server wraps both sides in `UPPER()`, making every indexed column non-sargable. The database collation is `SQL_Latin1_General_CP1_CI_AS` and SQLite's `LIKE` is ASCII case-insensitive, so plain `contains`/`startswith`/`exact` are already case-insensitive.
- `Solicitation.solicitation_number` is **prefix matched** (`_starts_q`) — it is a unique-indexed column on a table with hundreds of thousands of rows.
- `SolicitationLine` is the largest table in the search. Only probe `nsn`/`niin` when `terms.is_nsn_shaped`, and `nomenclature` when `terms.wants_text_scan`. A nomenclature `contains` is an unavoidable full scan, so it must never run for contract-number, IDIQ-number, or NSN-shaped terms.
- Keep `pk__in` sets under the SQL Server 2,100 parameter limit.

## DIBBS badge
The site-wide badge is app-owned by sales: `sales.context_processors.dibbs_notice_count`. It returns zero without querying for anonymous users, calls `sales.services.dibbs_notices.get_recent_notice_count()`, and caches `sales:dibbs_notice_recent_count:v1` for 1,800 seconds.

## Key files
- `core/views.py` — health endpoints, global search, API budget update.
- `core/urls.py` — `core:` URL namespace.
- `core/templates/core/global_search_results.html` — grouped Bootstrap result page.
- `core/management/commands/run_background_tasks.py` — scheduled-task dispatcher.
