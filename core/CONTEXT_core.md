# Core Context

## Purpose
`core` owns cross-cutting infrastructure that does not belong to a domain app: scheduled-task orchestration, API budget tracking, health endpoints, and the authenticated global portal search.

## Global portal search
- URL: `/core/search/` (`core:global_search`), GET only.
- Empty `q` redirects to `/home/` (`index`).
- The initial page materializes at most 10 rows per group. `?category=<category>&page=<n>` expands one group through Django `Paginator`.
- Match order is exact, starts-with, then contains.
- Contract searches always filter `Contract.company=request.active_company` and reuse `contracts.services.contract_number.normalize_contract_number`.
- Supplier searches are global, exclude `archived=True`, include aliases, and reuse `products.views._suppliers_matching_cage` for CAGE-shaped tokens.
- NSN searches are global and must use `products.nsn_utils.nsn_query_variants`; NSN, normalized NSN/NIIN, and part number are searched.
- Solicitation searches are global across `solicitation_number` and `SolicitationLine.nomenclature`.
- `SupplierNSNCapability` is not a search source.
- Querysets are materialized independently before the next model query to remain safe with SQL Server when MARS is disabled.

## DIBBS badge
The site-wide badge is app-owned by sales: `sales.context_processors.dibbs_notice_count`. It returns zero without querying for anonymous users, calls `sales.services.dibbs_notices.get_recent_notice_count()`, and caches `sales:dibbs_notice_recent_count:v1` for 1,800 seconds.

## Key files
- `core/views.py` — health endpoints, global search, API budget update.
- `core/urls.py` — `core:` URL namespace.
- `core/templates/core/global_search_results.html` — grouped Bootstrap result page.
- `core/management/commands/run_background_tasks.py` — scheduled-task dispatcher.
