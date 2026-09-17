# Core Agent Guide

Read `PROJECT_CONTEXT.md`, `core/CONTEXT_core.md`, `STATZWeb/settings.py`, and `STATZWeb/urls.py` before changing this app.

## Global search rules
- Preserve `@login_required` and GET-only behavior on `global_search` and `global_search_related`.
- The first paint is indexed matches only (`mode="fast"`). Do not run related hops or the nomenclature scan on that request. Those belong on `global_search_related` (`mode="deep"`) or `?complete=1` / `?category=` (`mode="full"`).
- `Contract` and `IdiqContract` results are non-negotiably scoped to `request.active_company`.
- Do not company-scope `Supplier`, `Nsn`, or `Solicitation`; these models have no company FK.
- Reuse `normalize_contract_number()`, `nsn_query_variants()`, and `_suppliers_matching_cage()` from their owning apps. PO search uses `Contract.po_number`, `Clin.clin_po_num`, and `PurchaseOrder.po_number` — never legacy `Clin.po_number`.
- Never use `SupplierNSNCapability` in global search.
- Relational expansion uses `Clin` for Contract ↔ Supplier ↔ Nsn, `IdiqContractDetails` for IDIQ ↔ Supplier ↔ Nsn plus `Contract.idiq_contract` for delivery orders, and sales line matches/RFQs for Solicitation ↔ Supplier. Every `Clin` relationship lookup must filter `Clin.company=request.active_company`, even though Supplier and Nsn themselves are global. IDIQ detail hops must filter `IdiqContract.company=request.active_company`.
- **Do not express relationships as OR'd joins in a group queryset.** Resolve them to primary keys first (`_direct_matches` → `_related_*_ids`) and filter the group with a single `pk__in`. The joined-OR version took over a minute in production; see the query-strategy section in `CONTEXT_core.md`.
- **Do not use case-insensitive lookups (`icontains`, `istartswith`, `iexact`) in search filters or ordering.** They emit `UPPER()` on SQL Server and disable every index. Use `_contains_q` / `_starts_q` / plain `contains`, `startswith`, `exact`; the collation handles case.
- Probe `SolicitationLine.nsn`/`niin` only when `terms.is_nsn_shaped` and `nomenclature` only when `terms.wants_text_scan`. It is the biggest table in the search and nomenclature matching is a full scan.
- Keep the query count per search bounded; `core/tests.py` asserts an upper bound.
- Keep SQL Server MARS disabled: finish `count()`/`list()` materialization for one queryset before querying another model.
- Expanded categories use Django `Paginator`; do not add hand-rolled offsets.
- Keep user input bounded and output encoded by Django templates.

## Shared-template rules
- Global launcher/header styling belongs in `static/css/app-core.css` under `#header`.
- Do not alter the fixed 48px `#header` height when adding controls.
- DIBBS recent-count logic belongs in `sales.services.dibbs_notices`; both the API and context processor reuse it.
- The badge context processor is authenticated-only and cached for 30 minutes.

## Verification
Run `python manage.py check`, targeted core search tests, template URL reversal checks, and authenticated/anonymous context-processor tests after edits.
