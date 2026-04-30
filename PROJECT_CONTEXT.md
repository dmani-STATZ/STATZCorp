# PROJECT_CONTEXT.md — STATZCorp Cross-App Reference

Read this file first when a task crosses app boundaries. It gives enough context to make confident decisions without reading every app's individual CONTEXT.md. For single-app work, go straight to that app's own CONTEXT.md and AGENTS.md instead.

---

## Repository Shape

Multi-app Django monolith. All apps share one process, one database, one auth layer, and one global base template. There is no microservice boundary — cross-app imports are common and intentional. Company-scoped tenancy flows through every request via `request.active_company`.

**Entry points:**
- `STATZWeb/settings.py` + `STATZWeb/urls.py` — global configuration and top-level URL routing
- `STATZWeb/middleware.py` + `users/middleware.py` — login enforcement, active-company injection
- `templates/base_template.html` — shared nav, CSS/JS, company selector; treat as a shared contract across all apps

---

## App Registry

### `contracts` — Core Contract Workspace
**Purpose:** Full contract lifecycle — headers, CLINs, notes, reminders, payments, shipments, folder tracking, SharePoint links, and exports.

**Owns:** `Contract`, `Clin`, `Company`, `PaymentHistory`, `Note`, `Reminder`, `ClinShipment`, `ContractSplit`, `FolderTracking`, `FolderStack`, `GovAction`, `AcknowledgementLetter`, `IdiqContract`, `IdiqContractDetails`, `Buyer`, `ContractType`, `ClinType`, `SpecialPaymentTerms`, `SalesClass`

**Consumes from other apps:**
- `products.Nsn` — FK on `Clin`
- `suppliers.Supplier` — FK on `Clin`; supplier CRUD views live here
- `processing.SequenceNumber` — PO/TAB number defaults on contract create
- `users.UserCompanyMembership`, `users.UserSettings` — company membership sync, reminder sidebar window

**Other apps consume from it:**
- `processing` — writes finalized records into `Contract`/`Clin`
- `sales` — reads `Clin` data via SQL views for Tier 1 NSN scoring
- `reports` — reads schema for AI-assisted query generation
- `transactions` — signal-tracks `Contract`, `Clin`, `ClinShipment` saves
- `products`, `suppliers` — URL routing forwards to `contracts` views

**URL prefix:** `/contracts/`

**Critical note:** Multi-tenant. Every queryset on company-scoped models must filter by `request.active_company`. Use `ActiveCompanyQuerysetMixin` on CBVs or manually filter in FBVs. Missing this leaks cross-tenant data.

#### SharePoint Integration

##### SharePoint Document Browser
Standalone document browser at `/contracts/documents/` lists and uploads files for a contract's SharePoint folder. It integrates with `contract_management.html` via a "Documents" button. Graph calls use client credentials flow (service principal), folder paths are stored in `Contract.files_url`, and the browser syncs contract context across tabs using `localStorage` plus a named window. It supports fallback to a parent/root folder and legacy path handling.

###### Layout (Popup-Optimized)

The documents browser is a popup-optimized layout: edge-to-edge, no max-width,
flex-column structure where only the file list scrolls. Header (with Save Path
+ Close Window), banner, horizontal breadcrumb, and toolbar (search + upload
button) are all flex-shrink: 0. The file list area has flex: 1 and is the drag-
drop target for uploads. No dedicated upload zone wastes vertical space.

###### New Folder

Users can create SharePoint folders from the toolbar via a modal (contract documents browser only; not shown for IDIQ-only browser). The folder is created at the current navigation path. Conflicts surface inline in the modal (not as page alerts). Backend: `create_folder()` in `contracts/services/sharepoint_service.py` uses `@microsoft.graph.conflictBehavior: "fail"` to detect duplicates cleanly. API: `POST /contracts/api/create-folder/` (`create_folder_api`).

##### SharePoint Path Resolution

Single source of truth: `Contract.get_sharepoint_relative_path()` in `contracts/models.py`.

Path priority (company config > settings > hardcoded default):

- Prefix: `company.sharepoint_documents_path` → `settings.SHAREPOINT_PATH_PREFIX` → `Statz-Public/data/V87/aFed-DOD`

Path patterns:

- Open regular: `{prefix}/Contract {number}/`
- Closed/Cancelled: `{prefix}/Closed Contracts/Contract {number}/`
- Open IDIQ DO: `{prefix}/Contract {idiq}/Delivery Order {number}/`
- Closed IDIQ DO: `{prefix}/Closed Contracts/Contract {idiq}/Delivery Order {number}/`

Status check uses `ContractStatus.description` in `('Closed', 'Cancelled')`.

`contracts/services/sharepoint_paths.py` validates `Contract.files_url` and delegates pattern paths to the model. **`resolve_contract_folder_path`** order: use `files_url` when modern (`source='files_url'`); otherwise `get_sharepoint_relative_path()` (`source='pattern'`); root prefix when the resolved path 404s in Graph.

Legacy `files_url` detection in `sharepoint_paths.resolve_contract_folder_path()`:

- Rejects UNC paths, drive letters, backslashes, URLs, non-prefix paths
- Falls through to pattern path when legacy detected
- Returns `legacy_detected` flag for frontend banner display

`legacy_detected` is surfaced on both `contract_details_api` and `sharepoint_files_api` GET responses; the browser shows a warning banner prompting the user to click **Save Path to Contract** to update `files_url` to the modern format. `fell_back_to_root` is surfaced on the files API when the resolved path 404s, prompting a separate banner.

---

### `processing` — Staging Pipeline
**Purpose:** Import queue and workflow buffer for contract/CLIN ingestion. PDF award parsing → staging records → finalized canonical contracts/CLINs.

**Owns:** `QueueContract`, `QueueClin`, `ProcessContract`, `ProcessClin`, `ProcessContractSplit`, `SequenceNumber`

**Consumes from other apps:**
- `contracts` — final write target (`Contract`, `Clin`, `ContractSplit`, `PaymentHistory`)
- `products.Nsn` — NSN matching during ingestion
- `suppliers.Supplier` — supplier matching during ingestion

**Other apps consume from it:**
- `contracts` — reads `SequenceNumber` for PO/TAB defaults

**URL prefix:** `/processing/`

**Critical notes:**
- IDIQ detection: type-code gate (`position[8] == 'D'` on stripped contract number) OR text gate ("Indefinite Delivery Contract"). Metadata packed into `QueueContract.description` as `IDIQ_META|TERM:12|MAX:350000|MIN:19`.
- `start_processing` routes IDIQ contracts to `idiq_processing_edit` via `redirect_url` in JSON response.
- Finalization (`finalize_contract`, `finalize_idiq_contract`) is the **only** write path into `contracts`. Runs inside `transaction.atomic`. Never write `Contract`/`Clin` from processing views outside finalization functions.
- Orphaned `QueueContract` rows (no contract number) can be reconciled via `match_contract_number` — uses `select_for_update()` to prevent race conditions.

---

### `suppliers` — Supplier Domain
**Purpose:** Supplier profiles, contacts, documents, certifications/classifications, AI enrichment pipeline, global AI model configuration.

**Owns:** `Supplier`, `Contact`, `SupplierDocument`, `SupplierCertification`, `SupplierClassification`, `SupplierType`, `OpenRouterModelSetting`

**Consumes from other apps:**
- `contracts.Contract`/`Clin` — metric aggregation on supplier detail dashboards
- `products.Nsn` — via `SupplierNSNCapability` join

**Other apps consume from it:**
- `contracts` — supplier CRUD form and views **live in contracts**, not here; this app owns models only
- `sales` — RFQ targets, quote records, Tier 1–3 supplier matching
- `processing` — supplier matching during contract ingestion
- `reports` — `OpenRouterModelSetting` endpoint for global AI model config

**URL prefix:** `/suppliers/`

**Critical note:** `OpenRouterModelSetting` is the global AI model store shared by both `reports` and `suppliers` enrichment. Renaming or restructuring this model requires updates in both apps.

---

### `products` — NSN Catalog
**Purpose:** Canonical NSN metadata catalog and supplier-NSN capability join table.

**Owns:** `Nsn`, `SupplierNSNCapability`

**Consumes from other apps:**
- `suppliers.Supplier` — via `SupplierNSNCapability`

**Other apps consume from it:**
- `contracts` — `Clin` FK to `Nsn`
- `processing` — NSN matching
- `sales` — Tier 1 NSN scoring, approved-source lookup

**URL prefix:** `/products/nsn/` — routes to `contracts.views.NsnUpdateView`/`NsnSearchView`; no standalone views

**Critical note:** Migrated table names are `contracts_nsn` and `supplier_nsn_capability`. Raw SQL and management commands must use these legacy names. NSN editing and search views live in `contracts`, not here.

---

### `transactions` — Field-Level Audit Log
**Purpose:** Records every field-level change on tracked models via save signals; surfaces a history modal; supports inline editing.

**Owns:** `Transaction` (generic FK change rows keyed to any model)

**Consumes from other apps:**
- `contracts.Contract`, `contracts.Clin`, `contracts.ClinShipment` (`pod_date` only), `suppliers.Supplier` — tracked via signals in `transactions/signals.py`
- `auth.User` — change attribution

**Other apps consume from it:**
- `contracts` templates — `transaction_modal.html` for inline edit + history panel
- `suppliers` detail — edit UI integration

**URL prefix:** `/transactions/`

**Critical note:** Signal-driven. `QuerySet.update()` bypasses save signals — audit rows will be silently skipped on tracked models. `transaction_modal.html` uses hardcoded `/transactions/...` URLs, not Django URL reversal.

---

### `sales` — DIBBS Procurement Workflow
**Purpose:** Solicitation triage → RFQ dispatch → quote capture → BQ export; DIBBS award file imports; Tier 1–3 supplier matching; saved filter presets.

**Owns:** `Solicitation`, `SolicitationLine`, `SupplierRFQ`, `GovernmentBid`, `DibbsAward`, `NsnProcurementHistory`, `SavedFilter`, `MassPassLog`, `SolPackaging`, `SAMEntityCache`

**Consumes from other apps:**
- `suppliers.Supplier` — RFQ targets, quotes
- `contracts.Clin` — Tier 1 NSN scoring via SQL view `dibbs_supplier_nsn_scored`
- `products.Nsn` — NSN matching, approved-source lookup

**Other apps consume from it:** Nothing — terminal system

**URL prefix:** `/sales/`

**Critical notes:**
- Three match tiers: T1 (`dibbs_supplier_nsn_scored` view — indexed `match_count` column, refreshed nightly), T2 (approved sources from `tbl_ApprovedSource`), T3 (FSC match).
- DIBBS PDFs fetched via Playwright in batches of 10 sessions.
- `NsnProcurementHistory` keyed on `(nsn, contract_number)` — `save_procurement_history` updates `last_seen_sol`/`extracted_at` only for existing keys; never overwrites price/quantity.
- Background task entry via `core/management/commands/run_background_tasks.py` → `sales/tasks/send_queued_rfqs.py`.

---

### `users` — Auth & Access Control
**Purpose:** Azure AD + password auth; app access registry; user portal; company membership; user settings; calendar sync.

**Owns:** `AppRegistry`, `AppPermission`, `UserSettings`, `UserOAuthToken`, `UserCompanyMembership`, `PortalSection`, `WorkCalendarEvent`

**Consumes from other apps:**
- `contracts.Company` — company membership and active-company state

**Other apps consume from it:**
- Every app — provides `request.active_company`, `request.user`, `conditional_login_required`, `AppPermission` gates, and context processors

**URL prefix:** `/users/`

**Shared infrastructure provided to the whole project:**
- `STATZWeb/middleware.py` `LoginRequiredMiddleware` — enforces auth globally; respects `settings.REQUIRE_LOGIN`
- `users/middleware.py` — injects `request.active_company` on every request
- `users/context_processors.py` — injects `user_preferences`, `active_company`, `system_messages`
- `contracts/context_processors.py` — injects reminder sidebar data (scoped by `active_company`)
- `STATZWeb.decorators.conditional_login_required` — per-view auth enforcement

---

### `reports` — Ad-Hoc SQL Reporting
**Purpose:** User-requested reports; staff-authored SQL queries; CSV exports; AI-assisted schema introspection via OpenRouter.

**Owns:** `ReportRequest` (status, SQL draft, execution history, category, last-run audit)

**Consumes from other apps:**
- `users.UserSettings` — per-user AI model preferences
- `suppliers.openrouter_config` / `OpenRouterModelSetting` — AI model endpoint
- Contract/supplier schema — read-only via `run_select`

**Other apps consume from it:** Nothing — read-only surface

**URL prefix:** `/reports/`

**Critical note:** SQL execution is strictly read-only via `run_select`/`is_safe_select` in `reports/utils.py`. Never bypass. `CORE_TABLES` in `reports/views.py` is a hardcoded schema prompt list — update it when core table names change.

---

### `training` — Compliance Training
**Purpose:** CMMC course matrix; completion tracking; document uploads; Arctic Wolf security awareness flow; PDF audit exports.

**Owns:** `Course`, `Account`, `Matrix`, `UserAccount`, `Tracker`, `TrainingDoc`, `ArcticWolfCourse`, `CourseReviewClick`

**Consumes from other apps:**
- `auth.User` — FK throughout

**Other apps consume from it:**
- `base_template.html` hardcodes `{% url 'training:dashboard' %}` in global nav — renaming this URL name breaks navigation for every app

**URL prefix:** `/training/`

**Critical notes:**
- `ArcticWolfCourse.slug` is auto-generated from `name` on every `save()` — renaming a live course silently invalidates all distributed completion URLs.
- `manage_matrix` is `@login_required` only — missing superuser guard (known gap).

---

### `accesslog` — Visitor Access Log ⚠️ Pending Deprecation
**Purpose:** Facility visitor check-in/check-out; staged visitor records; monthly PDF export.

**Owns:** `Visitor`, `Staged`

**Consumes from other apps:** None

**Other apps consume from it:** None — fully isolated

**URL prefix:** `/accesslog/`

**Deprecation note:** This app is planned for removal. Do not add new features, expand its models, or increase coupling to other apps. Bug fixes only until removal.

---

### `inventory` — Warehouse Stock Ledger
**Purpose:** Inventory catalog by NSN/description/location/quantity; live value dashboard; AJAX autocomplete.

**Owns:** `InventoryItem`

**Consumes from other apps:** `custom_currency` template filter (shared global)

**Other apps consume from it:** Nothing — standalone

**URL prefix:** `/inventory/`

---

### `tools` — PDF Utilities
**Purpose:** Staff-facing PDF merge, split, page-delete operations via web UI. No persistent models.

**Owns:** Stateless PDF operations (pypdf)

**Consumes from other apps:** None

**Other apps consume from it:** Nothing

**URL prefix:** `/tools/`

---

### `td_now` — Tower Defense Game
**Purpose:** Self-contained tower-defense game with map/campaign editors for staff content curation.

**Owns:** `Map`, `TowerType`, `EnemyType`, `Wave`, `Campaign`, `CampaignStage`, `StageWave`

**Consumes from other apps:** Django auth decorators only

**Other apps consume from it:** Nothing — fully isolated

**URL prefix:** `/td-now/`

---

## Cross-App Data Flow

```
[users] ── auth, active_company, AppPermission ──────────────────────► all apps
    │
    ▼
[contracts] ◄──── finalization ──── [processing] ◄── PDF award parsing
    │  Company/Contract/Clin            QueueContract/QueueClin
    │  SequenceNumber (read)            SequenceNumber (owned)
    │
    ├──► [transactions]  (signal-tracks Contract/Clin/Supplier saves)
    │
    ├──► [products]  Nsn ──────────────────────────────────┐
    │                                                       │
    └──► [suppliers]  Supplier ────────────────────────────┤
                                                           │
                                                    [sales] (reads Clin/Supplier/Nsn)
                                                    Solicitation/RFQ/Award → terminal

[reports] ── read-only SQL across contracts/suppliers schema
[training], [accesslog], [inventory], [tools], [td_now] ── fully isolated
```

---

## Shared Infrastructure Map

| What | Where it lives | Who uses it |
|---|---|---|
| Login enforcement | `STATZWeb/middleware.py` `LoginRequiredMiddleware` | All apps |
| Active company injection | `users/middleware.py` → `request.active_company` | `contracts`, `processing`, `suppliers`, `sales` |
| App access gates | `users.AppRegistry` / `AppPermission` | All feature apps |
| User settings | `users.UserSettings` | `contracts` (reminder window), `reports` (AI model) |
| Company membership | `users.UserCompanyMembership` | `contracts.CompanyForm` |
| Global AI model config | `suppliers.OpenRouterModelSetting` | `suppliers` enrichment, `reports` AI stream |
| Reminder sidebar context | `contracts/context_processors.py` | All templates extending `contract_base.html` |
| PO/TAB sequence numbers | `processing.SequenceNumber` | `processing` finalization into `contracts.Contract`; `initialize_sequence_numbers` management command |
| Field-change audit | `transactions/signals.py` | `contracts.Contract`, `contracts.Clin`, `contracts.ClinShipment` (`pod_date`), `suppliers.Supplier` |
| Background task registry | `core/management/commands/run_background_tasks.py` | `sales/tasks/`, other app task modules |
| CSS / design system | `static/css/theme-vars.css`, `app-core.css`, `utilities.css` | All templates |
| Microsoft Graph API token | `users.UserOAuthToken` | `sales` (RFQ mail) |

---

## Key Model Ownership Quick Reference

| Model | Owned by | FK'd / used by |
|---|---|---|
| `Company` | `contracts` | `Contract`, `Clin`, `UserCompanyMembership`, all company-scoped models |
| `Contract` | `contracts` | `Clin`, `ContractSplit`, `Note`, `PaymentHistory`, `FolderTracking` |
| `Clin` | `contracts` | `ClinShipment`, `Note`, `PaymentHistory`, `ClinAcknowledgment`; read by `sales` via SQL view |
| `Supplier` | `suppliers` | `Clin` FK, `Contact`, `SupplierDocument`, `SupplierNSNCapability`; tracked by `transactions` |
| `Nsn` | `products` | `Clin` FK, `SupplierNSNCapability`, `IdiqContractDetails`; table name `contracts_nsn` |
| `SequenceNumber` | `processing` | Read by `contracts.views.contract_views` for PO/TAB defaults |
| `Transaction` | `transactions` | Generic FK to any audited model; never written to directly from business logic |
| `AppPermission` | `users` | Checked in every feature view via middleware |
| `UserSettings` | `users` | `contracts` reminder window, `reports` AI model selection |
| `QueueContract` | `processing` | Parent of `QueueClin`; finalized into `Contract` |
| `Solicitation` | `sales` | `SolicitationLine`, `SupplierRFQ`, `GovernmentBid` |
| `ReportRequest` | `reports` | Nothing downstream |
| `OpenRouterModelSetting` | `suppliers` | `suppliers` enrichment views, `reports` AI stream endpoint |

---

## Cross-App Change Rules

### When changing `Contract` or `Clin` fields
Required updates: `contracts/models.py` + migration + `contracts/forms.py` + affected `contracts/views/*` + templates + `contracts/CONTRACTS_APP_CURRENT_STATE.md`.
Downstream: `processing/models.py` finalization mapping, `transactions/signals.py` tracked fields, `sales/services/matching.py` if CLIN supplier/NSN fields touched.

### When changing `Supplier` fields
Required: `suppliers/models.py` + migration + `contracts/forms.py` (`SupplierForm`) + `contracts/views/supplier_views.py` + `templates/suppliers/*` + `transactions/signals.py` + `sales/services/email.py` / matching flows.

### When changing `Nsn` fields
Required: `products/models.py` + migration + `contracts/forms.py` (`NsnForm`) + `contracts/views/nsn_views.py`/`idiq_views.py` + `processing` matching views + raw SQL in `SQL/migrate_data.sql` if table/column names change.

### When sending data from `processing` → `contracts`
Finalization is the only write path. Never write `Contract`/`Clin` from processing views outside of the finalization functions (`finalize_contract`, `finalize_idiq_contract`).

### When sending data from `contracts` → `sales`
`sales` reads via SQL views — it receives no pushed updates. Changes to `Clin` supplier/NSN fields can affect Tier 1 match counts; run `refresh_match_counts` after bulk changes.

### When using `request.active_company`
Injected by `users/middleware.py`. Every queryset on company-scoped data must filter by it. `ActiveCompanyQuerysetMixin` handles this on CBVs. Never query company-scoped models without this filter.

### When adding a new background task
Add a callable under the owning app's `tasks/` package, then register it in `core/management/commands/run_background_tasks.py`. Do not add ad-hoc management commands for recurring work.

### When adding a field that needs audit history
Add the field path to `transactions/signals.py` `TRACKED` dict. Never use `QuerySet.update()` on tracked models — it bypasses save signals.

### When renaming a URL name used outside its app
Run repo-wide search before changing. `training:dashboard` is hardcoded in `base_template.html`. `transactions` modal uses hardcoded `/transactions/...` paths. `reports` admin JS posts to `suppliers:global_ai_model_config`.

---

## CSS Architecture (All Apps)

No Tailwind. Bootstrap 5 plus three global CSS files:

- `static/css/theme-vars.css` — brand tokens for header and sidebar only: `--company-primary`, `--company-secondary`, `--header-height`. Spacelab Bootstrap 5.3 handles all other theming. Do not add surface, text, border, or button tokens here.
- `static/css/app-core.css` — all layout, component, button, and modal styles. New named classes go here.
- `static/css/utilities.css` — utility and helper classes.

When editing any template: replace Tailwind utility classes with Bootstrap 5 equivalents or named classes from `app-core.css`. Do not leave Tailwind classes in place. Button pattern: `.btn-outline-brand` (standard) and `.btn-outline-brand.btn-tinted` (pill with `#eff6ff` tint).
