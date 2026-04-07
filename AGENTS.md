# Repository AGENTS.md

## 1. Purpose of This File
This file defines repository-wide safe-edit rules for AI coding agents and developers working anywhere in this codebase.

Before significant edits, read project-level context first (`PROJECT_CONTEXT.md` when present), then relevant app-level `CONTEXT.md` and `AGENTS.md` files.

## 2. How to Start Work in This Repo
Use this reading order before editing:

- `PROJECT_CONTEXT.md` if it exists. It is currently not present in this repo.
- `PROJECT_STRUCTURE.md` plus `STATZWeb/settings.py` and `STATZWeb/urls.py` for global wiring.
- Target app `CONTEXT.md`.
- Target app `AGENTS.md`.
- Coupled app docs when changing shared concepts:
- `contracts` + `processing` + `transactions` for `Contract`/`Clin` changes.
- `suppliers` + `contracts` + `sales` + `transactions` for supplier changes.
- `products` + `contracts` + `processing` for `Nsn` changes.
- `users` + `STATZWeb/middleware.py` for auth/permissions/company-scoping changes.
- Shared global files as needed:
- `templates/base_template.html` for global URL reversals/navigation.
- `users/context_processors.py` and `contracts/context_processors.py` for globally injected context.

## 3. Repository Shape
This repository is a multi-app Django monolith with app-based ownership but strong cross-app coupling.

- Core domain center: `contracts`.
- Identity/permissions center: `users` plus `STATZWeb/middleware.py`.
- Staging-to-canonical pipeline: `processing` writes into `contracts`.
- Audit side effects: `transactions` signals on `Contract`, `Clin`, and `Supplier` saves.
- Supplier/NSN split ownership: `suppliers` and `products` models, but important UI/views in `contracts`.
- Reporting/export-heavy runtime: `contracts`, `sales`, `reports`, `training`, `tools`, `accesslog`, `users` all stream files.
- UI pattern mix: server-rendered templates with significant inline JS in several apps.
- Background pattern: no Celery/task queue files; most heavy work is synchronous request-time logic.

## 4. Global Safe-Edit Rules
- Keep changes scoped to the requested behavior. Do not do opportunistic cleanup in unrelated files.
- Edit in the owning app first, then update downstream consumers in the same change.
- Before renaming shared fields, URL names, templates, or JSON keys, run repo-wide search and update all call sites.
- Preserve global auth/permission flow in `STATZWeb/middleware.py`, `users` models/admin, and view decorators.
- Preserve company scoping (`request.active_company` and `contracts.views.mixins.ActiveCompanyQuerysetMixin`) for company-owned data.
- Do not bypass model `save()` on tracked models (`Contract`, `Clin`, `Supplier`) when audit history is required; `transactions` depends on save signals.
- Treat `templates/base_template.html` as a shared contract. URL-name changes there break multiple apps.
- Keep SQL execution guardrails in `reports/utils.py` (`run_select`, `is_safe_select`) and do not bypass them in views.
- Treat export/download endpoints as sensitive. Keep access controls, filters, and expected columns intact.
- Ignore legacy snapshot files unless explicitly asked (`contracts/views.orig`, `contracts/migrations/0002_create_views.py.bak`).

## 5. When Repo-Wide Search Is Mandatory
Run repo-wide search before any of these changes:

- Renaming fields on `contracts.Contract`, `contracts.Clin`, `suppliers.Supplier`, `products.Nsn`.
- Renaming URL names in any app namespace used outside that app (`contracts:`, `suppliers:`, `users:`, `reports:`, `inventory:`, `training:`, `tools:`).
- Renaming template paths used by includes/extends or cross-app render calls.
- Changing status/choice values used as raw strings in views/templates (`sales`, `processing`, `reports`, `training`).
- Changing JSON payload keys used by JS (`processing/static/processing/js`, `td_now/static/td_now`, `reports/templates/reports/admin_dashboard.html`, `templates/suppliers/supplier_enrich.html`).
- Changing permission/setting keys (`AppRegistry`, `AppPermission`, `UserSettings` names like `reports_ai_model`, `current_company_id`).
- Changing export/report columns or field mappings (`sales/services/bq_export.py`, `contracts` export views, `reports` SQL outputs).
- Changing signal or middleware behavior (`transactions/signals.py`, `users/signals.py`, `STATZWeb/middleware.py`, `users/middleware.py`).

## 6. Common Coupled Change Patterns
- `Contract`/`Clin` schema changes:
- `contracts/models.py` + migration + `contracts/forms.py` + relevant `contracts/views/*` + templates.
- Plus downstream: `processing/models.py` and finalization mapping, `transactions/signals.py`, and `sales/services/matching.py` when CLIN supplier/NSN fields are touched.
- `Supplier` schema changes:
- `suppliers/models.py` + migration + `contracts/forms.py` (`SupplierForm`) + `contracts/views/supplier_views.py` + `templates/suppliers/*` + `transactions/signals.py` + `sales/services/email.py`/matching flows.
- `Nsn` schema changes:
- `products/models.py` + migration + `contracts/forms.py` (`NsnForm`) + `contracts/views/nsn_views.py`/`idiq_views.py` + `processing` matching views + raw SQL references (`SQL/migrate_data.sql`) when table/column names change.
- Permission-registry changes:
- `users/models.py` (`AppRegistry`, `AppPermission`) + `users/admin.py` + `users/management/commands/*app*` + `STATZWeb/middleware.py`.
- Portal/calendar model changes:
- `users/models.py` + `users/forms.py` + `users/views.py` + `users/portal_services.py` + `users/urls.py`.
- URL/API changes:
- `urls.py` + callers in templates + inline/static JS.
- Special case: `transactions/templates/transactions/transaction_modal.html` uses hardcoded `/transactions/...` paths.
- Export flow changes:
- export view/service + template triggers + downstream consumers of filenames/columns.

## 7. App Boundary Rules
- `contracts` is the canonical source for contract/CLIN/company lifecycle data.
- `processing` is staging/workflow data. It should translate into `contracts` records, not duplicate canonical business rules long-term.
- `transactions` is downstream audit infrastructure. Do not move business logic there; keep it as observer/edit modal support.
- `suppliers` owns supplier models and enrichment logic, but supplier CRUD form/view flow is largely in `contracts`.
- `products` owns NSN models, but NSN editing/search views are wired from `contracts`.
- `sales` owns DIBBS-specific entities/workflows and consumes supplier/contracts data.
- `reports` owns `ReportRequest` workflow and read-only SQL tooling; it should not become a write path to core domain tables.
- `users` owns auth, app permissions, settings, active-company state, and portal APIs.
- Prefer extending existing owner workflows over duplicating business rules in another app.

## 8. Security / Permissions / Sensitive Data Rules
- Keep `STATZWeb.middleware.LoginRequiredMiddleware` behavior intact unless explicitly changing auth policy.
- Preserve `AppRegistry`/`AppPermission` checks and superuser/staff gates in views/admin actions.
- Preserve `request.active_company` enforcement when querying company-scoped models.
- Preserve object-level ownership checks where present (`reports` run/export, organizer-bound portal event edits).
- Maintain CSRF and method restrictions on mutating endpoints (many flows rely on JS `fetch` + CSRF tokens).
- Do not log or expose token fields (`users.UserOAuthToken`) or sensitive request payloads.
- Keep restrictive field allowlists on enrichment/update endpoints (`suppliers` apply enrichment, similar write APIs).
- Treat uploads/downloads as sensitive:
- PDF/file handlers in `tools`, `training`, `processing`, `contracts` should keep size/type/permission checks.
- `parse_procurement_history()` in `sales/services/dibbs_pdf.py` uses `pypdf.PdfReader` to extract text from raw PDF bytes. DIBBS serves `.PDF` files directly — not ZIPs. The old ZIP-based approach was incorrect and has been replaced. The `pypdf` package is a declared dependency in `requirements.txt`.
- **`NsnProcurementHistory`** rows are keyed on `(nsn, contract_number)`. `save_procurement_history()` inserts new rows with `first_seen_sol` / `last_seen_sol`; for existing keys it updates **`last_seen_sol`** and **`extracted_at`** only — it does not overwrite price, quantity, or other historical fields.
- Exports should remain authenticated and scoped.

## 9. Reporting / Export / Background Processing Rules
- Keep `reports` execution read-only via `run_select`; do not execute raw SQL directly in views.
- `reports/views.py` `CORE_TABLES` is a hardcoded schema prompt list. Update it when core table names change.
- `sales/services/bq_export.py` `COMPANY_FILLED_COLUMNS` is a strict column mapping contract. Field renames must update mapping.
- Validate export changes end-to-end in:
- `contracts` (CSV/XLSX and folder tracking exports),
- `sales` (BQ export),
- `reports` (CSV export),
- `training` and `accesslog` (PDF exports),
- `tools` (PDF/ZIP outputs),
- `users` (portal CSV export).
- There is no Celery task layer in this repo. Assume heavy processing is request-time and verify latency/error handling.
- `auto_import_dibbs` — **Loop A:** `fetch_dibbs_archive_files` (IN + BQ zip only; AS inside zip) + `run_import`. **Loop B:** set-aside harvest via `fetch_pdfs_for_sols` in **batches of 10** (one Playwright session per batch); persists `pdf_blob`; fifth failure sets `pdf_data_pulled`. **Loop C:** `parse_pdf_data_backlog` (ORM only); `save_procurement_history` uses raw `executemany` for inserts. No CA zip in `dibbs_fetch`. ORM never inside `sync_playwright()`.
- `fetch_pending_pdfs` — **Deprecated** as the default 5‑minute WebJob; nightly Loop B+C cover set-aside harvest + parse. Command remains for manual/RFQ-queue catch-up: batch-of-10 sessions, then `parse_pdf_data_backlog`. Max five fetch attempts per sol.
- The scraper may re-attempt a date that was partially imported. `_process_records()` in `sales/services/awards_file_importer.py` must filter out `notice_id` values that already exist before calling `executemany` to prevent `IntegrityError` on duplicate key (and filter `dibbs_award_mod` inserts against existing rows for the same unique constraint). All `IN` clause queries against large record sets must be chunked using `_chunked(list, AW_CHUNK)` to stay under SQL Server's 2,100 parameter limit. This applies to `existing_keys` and `existing_mod_awards` lookups in `_process_records()`.
- Signal-based automation exists in `transactions` and `users`; changing save paths or middleware can silently remove side effects.

## 10. Testing and Verification Expectations
Test coverage is uneven:

- `training/tests.py` has substantial coverage.
- Most other app `tests.py` files are stubs.

After behavior changes, expected verification is:

- Run `python manage.py check`.
- Run `python manage.py test training` at minimum.
- Run `python manage.py makemigrations --check` after model edits.
- Manually validate changed flows, including coupled apps.
- Re-test permissions and company scoping after queryset/view/middleware changes.
- Re-test admin pages after schema/form changes for registered models.
- Re-test exports/downloads after field/filter/status changes.
- If changing tracked `Contract`/`Clin`/`Supplier` fields, verify new edits still create `transactions.Transaction` rows.

## 11. Known Repo-Level Footguns
- Cross-app field references are often string-based in templates, JS, signals, and helper mappings; partial renames silently break behavior.
- `QuerySet.update()` bypasses save signals and can skip `transactions` audit recording.
- `templates/base_template.html` contains global URL reversals; URL-name changes can break navigation site-wide.
- `suppliers/urls.py` and `products/urls.py` route to `contracts` views; changes in `contracts` view names can break those apps at import time.
- `reports` admin JS depends on specific DOM IDs and posts to `suppliers:global_ai_model_config`; API/name drift breaks UI silently.
- `transactions` modal JS uses hardcoded `/transactions/...` endpoints, not Django URL reversal.
- Global auth behavior varies with `settings.REQUIRE_LOGIN`; undecorated views can become reachable in environments where login is off.
- Legacy snapshot files (`contracts/views.orig`, `.bak` migration file) can be mistaken for live code.

## 12. Standard Safe Change Workflow
1. Read project-level context (`PROJECT_CONTEXT.md` if present; otherwise `PROJECT_STRUCTURE.md`, `STATZWeb/settings.py`, `STATZWeb/urls.py`).
2. Read target app `CONTEXT.md` and `AGENTS.md`.
3. Identify owning app and coupled consumers.
4. Run repo-wide search for symbols you plan to change (fields, URL names, templates, JSON keys, settings keys).
5. Implement minimal scoped edits in owner and coupled files together.
6. Add/update migrations when schema changes.
7. Verify with commands and manual smoke tests across coupled flows.
8. Summarize affected apps, residual risk, and manual checks performed.
9. **`processing.services.pdf_parser`:** Keep award PDF parsing and queue ingestion (`parse_award_pdf`, `ingest_parsed_award`) independent of HTTP, request objects, and view-layer concerns. Call them only from orchestration code (e.g. `upload_award_pdf` in `processing_views.py`), not from middleware or template tags.

## 13. Escalation Triggers
Slow down and inspect deeply before editing when changes involve:

- `contracts.Contract`, `contracts.Clin`, `suppliers.Supplier`, or `products.Nsn` schemas.
- Auth/permission middleware or `AppRegistry`/`AppPermission` logic.
- `request.active_company` behavior or company-scoped query filtering.
- Signal behavior (`transactions/signals.py`, `users/signals.py`) or save-path refactors.
- Export/report SQL/output mappings.
- URL-name changes referenced in `templates/base_template.html` or shared partials.
- File upload/download handling, binary fields, or destructive delete/cascade behavior.
- Raw SQL/table-name changes (`SQL/` scripts, reports core table references).

## 14. Quick Reference
- First docs to read:
- `PROJECT_CONTEXT.md` (not currently present), then `PROJECT_STRUCTURE.md`.
- `STATZWeb/settings.py`, `STATZWeb/urls.py`.
- Target app `CONTEXT.md` and `AGENTS.md`.
- Most coupled areas:
- `contracts` <-> `processing` <-> `transactions`.
- `contracts` <-> `suppliers` <-> `sales`.
- `products` <-> `contracts` <-> `processing`.
- `users` permissions/company state <-> `STATZWeb/middleware.py`.
- Riskiest edit types:
- Shared model/field renames, URL-name renames, permission/middleware changes, signal/save-path changes, export mapping changes.
- Mandatory search triggers:
- shared model fields, URL names, template paths, status constants, JS payload keys, settings keys, signal tracked fields.
- Key verification steps:
- `python manage.py check`.
- `python manage.py test training`.
- `python manage.py makemigrations --check` (for model edits).
- Manual cross-app smoke tests for permissions, scoping, transactions history, and exports.
