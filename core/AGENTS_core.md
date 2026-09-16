# Core Agent Guide

Read `PROJECT_CONTEXT.md`, `core/CONTEXT_core.md`, `STATZWeb/settings.py`, and `STATZWeb/urls.py` before changing this app.

## Global search rules
- Preserve `@login_required` and GET-only behavior on `global_search`.
- `Contract` results are non-negotiably scoped to `request.active_company`.
- Do not company-scope `Supplier`, `Nsn`, or `Solicitation`; these models have no company FK.
- Reuse `normalize_contract_number()`, `nsn_query_variants()`, and `_suppliers_matching_cage()` from their owning apps.
- Never use `SupplierNSNCapability` in global search.
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
