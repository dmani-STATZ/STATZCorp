# Project Context

## 1. Project Overview
This repository is a multi-app Django monolith for government/defense-style operations workflows centered on contracts, CLIN-level processing, supplier/product data, sales/import pipelines, compliance training, and reporting.

At a system level, the codebase appears to support:
- Contract lifecycle and contract-line (CLIN) management (`contracts`)
- Intake/queue/finalization processing for incoming contract data (`processing`)
- Sales-side solicitation/RFQ/bid workflows and imports (`sales`)
- Supplier and NSN capability management (`suppliers`, `products`)
- User/company context, app-level access control, and portal/calendar features (`users`)
- Reporting and export surfaces, including SQL-backed reports (`reports`)
- Transaction/audit-style change logging (`transactions`)
- Support modules for inventory, visitor logging, tooling, and training.

This is primarily server-rendered Django (views/forms/templates), with targeted AJAX/JSON endpoints and several export/report endpoints.

## 2. Repository Structure
Top-level layout (verified from repository tree):
- Django project package: `STATZWeb/`
  - Core settings and routing: `STATZWeb/settings.py`, `STATZWeb/urls.py`
  - Global middleware and decorators: `STATZWeb/middleware.py`, `STATZWeb/decorators.py`
- Feature apps: `users/`, `inventory/`, `contracts/`, `sales/`, `accesslog/`, `td_now/`, `processing/`, `training/`, `reports/`, `suppliers/`, `products/`, `tools/`, `transactions/`
- Shared UI assets:
  - Global templates: `templates/` (notably `templates/base_template.html`)
  - Static assets: `static/` (plus collected `staticfiles/`)
  - Tailwind/theme app: `theme_tw/`
- Ops/support files:
  - `manage.py`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`
  - Deployment/environment artifacts: `Procfile`, `startup.sh`, `web.config`, `.deployment`
  - SQL scripts folder: `SQL/`
  - Existing repo map doc: `PROJECT_STRUCTURE.md`
- Per-app context docs are present for all listed domain apps (each app has `CONTEXT.md`).

## 3. Major Apps and Ownership Boundaries
`STATZWeb` (project package)
- Owns global configuration: settings, URL composition, login-required and app-permission middleware behavior.
- Does not own business domain data itself; it orchestrates shared runtime behavior.
- Type: core platform glue.

`users`
- Owns authentication-adjacent behavior, user settings/preferences, app-level permission mapping (`AppRegistry`/`AppPermission`), user-company membership, and portal/calendar-related features.
- Does not own contracts/supplier/product transactional domain records.
- Type: core support/security context app.

`inventory`
- Owns inventory item/category/location records and related CRUD/views.
- Appears mostly standalone relative to core contract-processing flows.
- Type: peripheral support app.

`contracts`
- Owns major core domain entities (companies, contracts, CLINs, reminders/notes, payment/history-like records, splits, and related admin/support tables).
- Serves as foundational data for processing, reports, transactions logging, and some sales matching.
- Type: central core domain app.

`sales`
- Owns sales-side workflows: solicitations, RFQ/bids, importer flow, customer/contacts, and supplier capability mapping in sales context.
- Pulls from or aligns with contract/CLIN and supplier data but keeps much of its own model surface.
- Type: core workflow app (partially decoupled data model).

`accesslog`
- Owns visitor logbook/check-in/check-out flows with templates and PDF/report generation.
- Does not appear deeply coupled to contracts/processing domains.
- Type: operational support app.

`td_now`
- Owns TD Now-specific routes, views, context processor, and management commands.
- Appears as an integration/feature module with limited direct cross-app ownership.
- Type: specialized integration/support app.

`processing`
- Owns processing queue/staging/finalization pipeline for contract/CLIN intake and workflow state.
- Writes into/finalizes against `contracts` entities and maintains sequencing/queue records.
- Type: central core workflow app tightly coupled to `contracts`.

`training`
- Owns training/compliance-like entities (requirements, records, assignments, matrix view) and supporting views/forms.
- Mostly independent from contract-processing data model.
- Type: support/compliance app.

`reports`
- Owns report request records and a broad report/export/query surface, including SQL-backed report execution helpers and AI-assistant endpoints.
- Depends on many other apps' data; generally does not own source-of-truth business entities.
- Type: reporting/export app with high read coupling.

`suppliers`
- Owns supplier master data, addresses, supplier-user links, uploads, and some settings/config utilities.
- Shares schema coupling with `contracts` tables and connects to product/NSN capabilities.
- Type: core reference/master-data app.

`products`
- Owns NSN-related product records and supplier capability association (`SupplierNSNCapability`).
- Depends on suppliers and historically shares table namespace conventions with contracts.
- Type: core reference-data app.

`tools`
- Owns utility/tool endpoints and templates for operational helpers.
- Minimal domain ownership compared with contracts/processing/sales.
- Type: utility app.

`transactions`
- Owns generic change-log/audit-style transaction records and middleware/signal integration for tracking model changes.
- Does not own primary business entities; records cross-domain events.
- Type: cross-cutting audit/support app.

## 4. High-Level Architecture
- Multi-app Django monolith with a single project package (`STATZWeb`).
- Predominantly server-rendered architecture:
  - URLConfs per app
  - Function-based and class-based views
  - Django templates/forms for most workflows
- Centralized request gating and app-level access:
  - Login behavior via project middleware (`LoginRequiredMiddleware`)
  - App-level access control via `users.AppRegistry`/`users.AppPermission` checks in middleware.
- Company-scoped runtime context:
  - `users.middleware.ActiveCompanyMiddleware` injects active company behavior used across apps.
- Reporting/export architecture is mixed:
  - Template-driven reports
  - CSV/XLSX/PDF outputs in multiple apps
  - SQL-backed dynamic report execution in `reports`.
- Background architecture is light:
  - No clear Celery/task queue footprint in repository code
  - Uses signals and management commands for asynchronous/batch-like concerns.

## 5. Cross-App Relationships
Most important coupling points (verified via models/imports/URL surfaces):

- `contracts` is the central data hub.
  - `processing` imports and updates `contracts` models (`Contract`, `Clin`, related entities) during finalize/update paths.
  - `transactions` signals track changes on `contracts.Contract` and `contracts.Clin`.
  - `sales` services include matching/backfill patterns tied to contract/CLIN data.

- `users` depends on `contracts.Company`.
  - `UserCompanyMembership` and active-company middleware establish a cross-app tenancy/context pattern.
  - This context affects navigation and request behavior in many pages.

- Supplier/product coupling:
  - `products.Nsn` and `products.SupplierNSNCapability` link with `suppliers.Supplier`.
  - `contracts` imports product/supplier models in key model definitions.
  - `suppliers` and `products` use legacy `contracts_*` table naming patterns, increasing schema coupling risk.

- Reporting fan-in:
  - `reports` and report/export endpoints consume data from contracts, sales, supplier, and user settings contexts.
  - Report query tooling (`reports/utils.py`, `reports/views.py`) is a high-impact cross-domain read surface.

- Shared security and feature gating:
  - App permissions in `users` are enforced globally in project middleware, so app-level routing and permission records are coupled.

- Audit trail coupling:
  - `transactions` middleware/signals provide cross-app tracking, creating side effects on save/update for selected models.

## 6. Shared Technical Patterns
Recurring implementation patterns across repository:

- Heavy use of Django function-based views plus app-specific URL modules.
- Mixed placement of business logic:
  - Some logic in model methods/managers
  - Significant workflow logic in views (notably `processing` and parts of `contracts`/`sales`)
  - Service modules used selectively (example: `sales/services/*`, report helpers).
- Forms + templates are primary UI pattern; AJAX JSON endpoints exist for partial interactions.
- Admin usage is present across apps but operational workflows are often custom views rather than admin-only.
- Report/export patterns appear in multiple apps rather than a single export layer.
- Management commands are used in several apps for setup/sync/maintenance tasks.
- Signals are used for user/profile initialization and transaction logging; signal side effects are part of runtime behavior.
- Style maturity is mixed: some modernized modules coexist with legacy naming/table conventions and monolithic view files.

## 7. Request, Data, and Workflow Surface
Main visible workflow categories:

- Core contract workflows (`contracts`)
  - Dashboard/search/details/update flows
  - CLIN-level operations
  - Notes/reminders and related tracking
  - Contract log and export endpoints

- Processing pipeline (`processing`)
  - Queue and batch intake
  - Start/process/finalize/cancel transitions
  - Matching/assignment paths
  - CSV template/download/upload and import utilities
  - Finalization writes or links into core contract/CLIN data

- Sales workflows (`sales`)
  - Solicitations/RFQ/bid management
  - Multi-step import workflows
  - Supplier capability and customer contact operations
  - Export/report surfaces around bids and imports

- Reference/master data workflows (`suppliers`, `products`)
  - Supplier onboarding/maintenance
  - NSN and supplier capability management

- User/security/context workflows (`users`)
  - Login/logout/register/password reset
  - Company switching and preferences
  - App permission/configuration surfaces
  - Calendar/portal API and event views

- Reporting/export workflows (`reports`, plus contract/sales exports)
  - Dynamic report requests
  - SQL-backed report execution with safety checks
  - Download endpoints for CSV/XLSX/PDF-style outputs

- Support workflows
  - Visitor check-in/out and logs (`accesslog`)
  - Compliance/training records and matrix (`training`)
  - Utility pages/tools (`tools`)
  - TD Now-specific operational pages (`td_now`)

## 8. Security / Permissions Shape
Visible project-level security posture:

- Authentication:
  - Login enforcement is centralized via middleware (`STATZWeb.middleware.LoginRequiredMiddleware`) and a `REQUIRE_LOGIN` setting.
  - Additional `conditional_login_required` decorator exists for opt-in behavior.

- Authorization:
  - App-level access appears centrally enforced via `users.AppRegistry` + `users.AppPermission` checks in middleware.
  - Superusers bypass app permission checks.
  - Some views remain explicitly `@login_required`; enforcement is a mix of middleware and per-view decorators.

- Company scoping:
  - Active company middleware influences request context and data scope behavior in downstream apps.

- Sensitive surfaces:
  - Export/report endpoints (CSV/XLSX/PDF/SQL query) represent data exfiltration risk if permissions are misconfigured.
  - SQL report tool includes read-only style checks, but still requires careful review when extending.

- Auditability:
  - `transactions` captures selected model changes via middleware/signals.
  - `accesslog` provides a separate operational visitor trail.

- Notable consistency risk:
  - There are endpoints in support apps that are less explicit about access restrictions than core app patterns, so permission review should be part of change work.

## 9. Reporting / Export / Background Processing
Reporting/export:
- Dedicated `reports` app includes request objects, report utilities, SQL execution helpers, and admin-assistant-related endpoints.
- `contracts` and `sales` also include domain-specific exports and report-like responses.
- Export logic is distributed, not centralized; schema/field changes can break multiple output paths.

Background/batch processing:
- No clear Celery infrastructure in the repository.
- Batch behavior is implemented through:
  - Management commands in `users`, `contracts`, `STATZWeb`, `td_now`
  - Stepwise processing views/services in `processing` and `sales` import flows
  - Signals for automatic side effects (`users`, `transactions`)

Why this matters:
- Long-running or stateful workflows live in request/management-command paths, so race conditions/state transitions deserve extra validation.
- Distributed export/report code increases blast radius of model changes.

## 10. Testing Shape
Project-level testing profile appears uneven:
- `training` has substantive tests.
- Many other apps have minimal/placeholder `tests.py` or limited coverage.
- High-coupling areas (`contracts`, `processing`, `reports`, `sales`) do not appear to have comprehensive visible coverage proportional to complexity.

Practical implication:
- Manual verification and targeted test additions are important for cross-app changes, especially around processing finalization, exports, and permission-gated flows.

## 11. Main Risk Areas
Highest project-level footguns:

- Cross-app model/schema changes:
  - `contracts` field/table changes can affect `processing`, `transactions`, `reports`, and parts of `sales`.

- Legacy table naming and shared DB assumptions:
  - `suppliers`/`products` models mapped to `contracts_*` table names increase migration/refactor risk.

- Distributed report/export dependencies:
  - Renaming fields or queryset shapes can silently break CSV/XLSX/PDF/SQL report endpoints in multiple apps.

- Workflow state transitions in `processing`:
  - Queue/start/finalize/cancel logic is complex and mostly view/service-driven.

- Middleware-level permission coupling:
  - App permission records and URL namespaces must stay consistent with `AppRegistry`/middleware expectations.

- Signal side effects:
  - `transactions` and `users` signals introduce non-local behavior on save/update paths.

- Inconsistent hardening in peripheral endpoints:
  - Some support app views show weaker explicit auth/error handling patterns than core app flows, raising maintenance risk.

## 12. How to Approach Changes Safely
Recommended safe-change workflow for this repository:

1. Read this file (`PROJECT_CONTEXT.md`) for system map.
2. Read target app `CONTEXT.md` and then verify in code (`models.py`, `views.py`, `urls.py`, `forms.py`, `services/`).
3. Before renaming fields/models/tables, run repo-wide search across coupled apps (`contracts`, `processing`, `reports`, `sales`, `transactions`, templates).
4. For workflow changes, trace full request path:
   - URL route -> view -> form/service/model -> templates/export endpoints -> signals/middleware side effects.
5. For permission-sensitive changes, verify both:
   - Per-view decorators and checks
   - Middleware-level app permission behavior.
6. For reporting/export changes, test at least one representative endpoint in each affected app.
7. For processing/sales imports, validate state transitions and rollback/error paths with realistic sample data.
8. Add or extend tests in touched domains; if coverage is thin, document manual verification steps explicitly in PR notes.

## 13. Recommended Reading Order
Suggested onboarding order for engineers/AI agents:

1. `STATZWeb/settings.py` and `STATZWeb/urls.py`
2. `STATZWeb/middleware.py` and `STATZWeb/decorators.py`
3. `templates/base_template.html` (global navigation and cross-app UI assumptions)
4. `PROJECT_STRUCTURE.md` and target app `CONTEXT.md`
5. Central domain apps:
   - `contracts/models.py`, `contracts/urls.py`, key `contracts/views/*`
   - `processing/models.py`, `processing/urls.py`, key processing views/services
6. Security/context layer:
   - `users/models.py`, `users/middleware.py`, `users/urls.py`
7. Coupled reference data:
   - `suppliers/models.py`, `products/models.py`
8. Reporting/export layer:
   - `reports/views.py`, `reports/utils.py`, export-heavy views in `contracts` and `sales`
9. Cross-cutting side effects:
   - `transactions/models.py`, `transactions/signals.py`, `users/signals.py`
10. Peripheral/support apps as needed (`inventory`, `accesslog`, `training`, `tools`, `td_now`)

## 14. Known Gaps / Ambiguities
- Deployment/runtime topology is not fully explicit from repo alone (multiple deployment artifacts exist, but no single authoritative operations doc in inspected files).
- Some app `CONTEXT.md` summaries are partially stale relative to code (for example, evolving import/processing/report surfaces), so code remains source of truth.
- Ownership boundaries between `contracts`, `suppliers`, and `products` are historically intertwined due table naming and cross-import patterns.
- `td_now` and some utility/support app business criticality is not fully clear from code alone.
- Test coverage signal is limited by many minimal test modules; risk assessment here is based on visible tests and complexity concentration.

## 15. Quick Reference
- Central apps:
  - `contracts`, `processing`, `users`, `sales`, `suppliers`, `reports`
- Reporting-heavy apps:
  - `reports` (primary), plus export surfaces in `contracts` and `sales`
- Likely support/utility apps:
  - `inventory`, `accesslog`, `training`, `tools`, `td_now`, `transactions` (cross-cutting support)
- Most coupled areas:
  - `contracts` <-> `processing`
  - `contracts` <-> `suppliers`/`products`
  - `reports` consuming many apps
  - `users` middleware/permissions affecting all routed apps
  - `transactions` signals on core model changes
- Riskiest edit types:
  - Cross-app field/table renames on core models
  - Processing state machine/finalization logic changes
  - Report/export query/output contract changes
  - Permission/middleware/app-registry changes
- First files/docs to read:
  - `PROJECT_CONTEXT.md`
  - `STATZWeb/settings.py`
  - `STATZWeb/urls.py`
  - `STATZWeb/middleware.py`
  - target app `CONTEXT.md`
  - coupled app model/view/service files

