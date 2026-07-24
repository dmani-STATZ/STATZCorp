# PROJECT_CONTEXT.md — STATZCorp Cross-App Reference

Read this file first when a task crosses app boundaries. It gives enough context to make confident decisions without reading every app's individual CONTEXT_<app>.md. For single-app work, go straight to that app's own CONTEXT_<app>.md and AGENTS_<app>.md instead.

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

##### Open in Explorer

Read-only derivation maps a contract's SharePoint drive-relative folder path to a local OneDrive path so users can open the folder in Windows Explorer from the document browser **Actions** menu.

**Settings** (in `STATZWeb/settings.py`, near `SHAREPOINT_PATH_PREFIX`):

- `EXPLORER_SHAREPOINT_STRIP_PREFIX` — SharePoint prefix stripped before mapping (currently `Statz-Public/data/V87`)
- `EXPLORER_LOCAL_MOUNT` — local OneDrive mount under `%USERPROFILE%` (currently `OneDrive - statzcorpgcch/Statz - V87`)

The library version token (**V87**) also appears in `SHAREPOINT_PATH_PREFIX`; bump all three together on a library version change.

**Helper:** `build_explorer_uri()` in `contracts/services/sharepoint_paths.py` — pure function, no Graph/I/O. Returns a `statzfile:///` URI or `''` when the path cannot be mapped (legacy UNC, URLs, unknown root). Callers hide the Explorer action when the result is empty.

**URI scheme:** `statzfile:///` — resolved by the desktop handler under `%USERPROFILE%`.

**Desktop handler:** `deploy/explorer-handler/` (`open-explorer.ps1`, `statzfile.reg`, README). Deploy script to `C:\ProgramData\STATZ\`; register protocol via Intune. Requires Edge **AutoLaunchProtocolsFromOrigins** for the STATZ web origin.

**API surfaces:** `explorer_uri` on folder rows (`_folder_payload`) and `folder_weburl_api`; `current_explorer_uri` on `contract_details_api` and `sharepoint_files_api` GET responses. Intake draft browser reuses the same template/service automatically.

Path construction is **not** duplicated — derivation uses the same drive-relative paths already returned by SharePoint listing and `Contract.get_sharepoint_relative_path()` resolution.

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
- `IdiqContract` now has an `alert_note` TextField. When non-blank, both Processing (`ProcessContractUpdateView`) and Intake (DO draft editor) display a Bootstrap modal popup when the IDIQ is matched or when the edit page loads with an IDIQ already linked. The field is writable from the IDIQ processing editor, Intake IDIQ draft editor, and the contracts IDIQ edit page.

---

### `intake` — Contract Intake Queue
**Purpose:** JSON-backed draft workspace for new contracts before finalization into `contracts`. Replaces processing queue over time; independent of processing staging tables.

**Owns:** `DraftContract` (with `company` FK and `sharepoint_folder_status`), `AwardLedger` (table `intake_award_ledger` — the sole durable award→draft→live-contract lifecycle record), Pydantic schemas, soft locks, PDF/DIBBS ingestion, finalization into canonical tables

**Consumes from other apps:**
- `contracts.Company`, `contracts.Contract` — company scoping, dedup badge, finalization target, ledger live-contract link
- `sales.CompanyCAGE` (`dibbs_company_cage`) — CAGE → company resolution at DIBBS injection; ledger our-CAGE scoping
- `sales.DibbsAward` / `DibbsAwardMod` / `WeWonAward` — ledger mirror source (read-only)
- `contracts.services.sharepoint_service` / `sharepoint_paths` via `intake/services/sharepoint_intake.py` — folder path build, probe, create (no `processing.*` imports)

**Other apps consume from it:** The `sales` nightly scrape (`scrape_awards`) and daytime hot poll (`poll_we_won_today`) call `intake.services.award_ledger.upsert_ledger_for_batch(batch, ...)` in a guarded piggyback block — the same injection pattern as `queue_we_won_drafts`.

**URL prefix:** `/intake/` (queue at `/intake/`; read-only Award Ledger page at `/intake/ledger/` → `intake:award_ledger`)

**Critical notes:**
- Drafts are deleted on successful finalization; `DraftContract` is not audited by `transactions`
- SharePoint folder path lives in `data['sharepoint_folder_path']`; status in `sharepoint_folder_status`
- DO drafts derive SharePoint folder paths from the parent IDIQ's actual `files_url`
  (via `resolve_idiq_folder_path()`), not the default prefix pattern. Path shape:
  `{idiq_resolved_path}/Delivery Order {do_number}/`. Auto-resolution at DIBBS
  ingestion via `Award_Basic_Number` (`seed_do_draft_sp_path` in `queue_we_won_drafts`);
  re-resolution when an analyst applies an IDIQ match in the editor. User-confirmed
  paths (`sharepoint_folder_status == 'exists'`) are never overwritten.
- DIBBS piggyback (`queue_we_won_drafts`) probes SharePoint only when `company` resolves; never creates folders at injection time
- Draft documents browser at `/contracts/documents/draft/` (owned by contracts URL space, intake-authorized)
- SharePoint folder path carried to `Contract.files_url` at finalization
- DIBBS PDF fetch: fetch_and_apply_dibbs_pdf in intake/services/dibbs_pdf_fetcher.py. URL pattern confirmed: Award/IDIQ/PO  dibbs2.bsm.dla.mil/Downloads/Awards/{DDMONYY}/{contract_number}.PDF; DO  {idiq}{do}.PDF. Requires make_dibbs2_session() (DOD cookie). Stored in data['award_pdf_url'] at injection time.
- **Award Intake Ledger (`AwardLedger`):** the only durable record of the award→draft→live-contract journey (drafts + their `final_contract` link are deleted on finalize). Maintained by `intake/services/award_ledger.py`; latched write-once `*_at` timestamps + advance-only `lifecycle_state`. Updated from the scrape/poll piggyback (`upsert_ledger_for_batch`), the finalize hook (`stamp_live_contract` in `intake/finalize.py`), and the nightly `reconcile_award_ledger` background task. Backfill: `python manage.py backfill_award_ledger [--days N]`.
- **Award Ledger page (`intake:award_ledger`, `/intake/ledger/`):** read-only `AwardLedgerListView` — GET filters/sort/pagination + scoped CSV export (`?export=csv`). No company FK on the model, so scoping is by CAGE via `sales.CompanyCAGE` (superusers see all). Sort is whitelisted with a deterministic MSSQL tiebreak; `lifecycle_state` orders by `LIFECYCLE_RANK`. Nav link lives in the `draft_queue.html` header.

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

**Owns:** `Solicitation`, `SolicitationLine`, `SupplierRFQ`, `GovernmentBid`, `DibbsAward`, `DibbsAwardMod`, `DibbsNotice`, `NsnProcurementHistory`, `SavedFilter`, `MassPassLog`, `SolPackaging`, `SAMEntityCache`

**Consumes from other apps:**
- `suppliers.Supplier` — RFQ targets, quotes
- `contracts.Clin` — Tier 1 NSN scoring via SQL view `dibbs_supplier_nsn_scored`
- `products.Nsn` — NSN matching, approved-source lookup

**Other apps consume from it:**
- `contracts` — reads matched `DibbsAwardMod` rows via `sales/services/contract_mods.py` (`mods_for_contract`) for the Modifications section on the contract management page; acknowledgement via `POST /sales/contract-mods/<pk>/acknowledge/`

**URL prefix:** `/sales/`

**URL surface (portal):** `/sales/dibbs-notices/api/` — JSON feed of DIBBS public notices for the portal home page; returns up to 30 notices and a `recent_count` of notices posted within the last 7 days.

**Critical notes:**
- Three match tiers: T1 (`dibbs_supplier_nsn_scored` view — indexed `match_count` column, refreshed nightly), T2 (approved sources from `tbl_ApprovedSource`), T3 (FSC match).
- DIBBS PDFs fetched via Playwright in batches of 10 sessions.
- `NsnProcurementHistory` keyed on `(nsn, contract_number)` — `save_procurement_history` updates `last_seen_sol`/`extracted_at` only for existing keys; never overwrites price/quantity.
- **Manual SQL deploy boundary:** `sales/sql/usp_process_award_staging.sql` and the production `dibbs_we_won_awards` view are not managed by Django migrations. Every SQL-file change must be redeployed manually via SSMS to every environment; an application deploy alone can leave production on stale SQL. Bump the in-body `PROC_VERSION` and `sales/services/proc_versions.py` together. `python manage.py verify_stored_procs` compares live vs expected `PROC_VERSION` and INSERT column coverage; it exits non-zero on drift for CI/on-demand use. Startup runs it non-blocking (CRITICAL log, continue). It does not replace manual deployment.
- **`scrape_awards` resilience:** Per-date failures are isolated (batch → `FAILED`, loop continues). `MAX_CONSECUTIVE_FAILURES = 3` aborts the remaining queue on systemic faults. Import failures delete that `stage_id`'s staging rows before re-raising. Post-import WARNING when imported awards have empty `award_basic_number_url` (`possible stored proc drift`).
- **Stale award staging cleanup:** `python manage.py purge_stale_award_staging --older-than-hours=24 --dry-run` reports orphaned rows belonging only to stale `IN_PROGRESS` / `FAILED` scrape batches; omit `--dry-run` to delete those rows and their matching staging errors. Primary orphan cleanup is on the import failure path where `stage_id` is known. Never blanket-truncate staging tables.
- Background tasks registered via `core/management/commands/run_background_tasks.py` and scheduled per-task in `core.ScheduledTask` (`interval_minutes`, `run_order`). The WebJob heartbeat fires every 1 minute (`0 * 11-22 * * *`, 6 AM–5 PM CT window).
  1. `send_queued_rfqs` (5 min): Sends queued RFQs.
  2. `poll_we_won_today` (15 min): Daytime we-won award detection.
     - Service: `sales/services/poll_we_won_today.py` (wrapped in `sales/tasks/poll_we_won_today.py`).
     - Activation: Controlled by `WE_WON_POLL_ENABLED=true` environment variable (feature is off by default).
     - Session: Uses `make_www_session()` from `sales/services/dibbs_session.py` (requests-only, no Playwright).
     - Storage & Reconciliation: Inserts batches into `AwardImportBatch` with source `SOURCE_HOT_POLL` (`"hot_poll"`). This batch source is never touched by the nightly `scrape_awards` reconciliation.
     - Schedule: Every 15 minutes during the WebJob business-hours window (6 AM–5 PM CT).
     - Backstop: The nightly `scrape_awards` continues unchanged as the full-day backstop for all contractors, and naturally dedupes hot-poll captured awards by award number.
  - **Mod leak gate (hot poll):** `parse_awdrecs_html` must populate `Last_Mod_Posting_Date` (and related AW columns) so `import_aw_records` → `usp_process_award_staging` classifies MOD rows into `dibbs_award_mod` instead of `dibbs_award`. Rows with a populated mod posting date must not enter `WeWonAward` / Intake draft injection.
  - **`DibbsAwardMod` contract link:** `matched_contract` (FK → `contracts.Contract`, exact `contract_number` match via `contracts/services/contract_number.normalize_contract_number`), `acknowledged_at`, `acknowledged_by`. Matching runs after each `import_aw_records` / `import_aw_file` when `awardee_cage` is in active `CompanyCAGE` **or** `sales/constants.py::PARTNER_CAGES` (currently ETP / `64W95`). Backfill (`0052`) iterates `contracts.Contract` — not CAGE-filtered — so partner-managed contracts are included when the contract number exists in DB. Contract-page display: `sales/services/contract_mods.py` (`mods_for_contract`, `build_award_record_url`).
  3. `check_dibbs_notices` (1440 min / daily): Scrapes `www.dibbs.bsm.dla.mil` homepage for public DIBBS Notices using `make_www_session()` (requests only — no Playwright). Upserts new rows into `DibbsNotice` via `get_or_create` on `(title, posted_date)`; never overwrites existing rows.
  8. `reconcile_award_ledger` (1440 min / daily, run_order 8): `intake/tasks/reconcile_award_ledger.py`. Full backstop for the Award Intake Ledger — runs `intake.services.award_ledger.reconcile_open_ledger_rows()` across all open rows (draft-worked proxy + live-contract backstop + advance-only `lifecycle_state`). Catches finalize-hook misses and stragglers. Seeded by `core/migrations/0004_seed_reconcile_award_ledger_task.py`.
- `DibbsNotice` rows are keyed on `(title, posted_date)`. Use `get_or_create` only. `external_url` is resolved to absolute URL at scrape time and stored; never re-updated. Do not use Playwright for notice scraping — `make_www_session()` is sufficient.

---

### `users` — Auth & Access Control
**Purpose:** Azure AD + password auth; app access registry; user portal; company membership; user settings; calendar sync.

**Owns:** `AppRegistry`, `AppPermission`, `UserSettings`, `UserOAuthToken`, `UserCompanyMembership`, `PortalSection`, `WorkCalendarEvent`, `ReleaseNote`, `ReleaseNoteAcknowledgement`

**Consumes from other apps:**
- `contracts.Company` — company membership and active-company state

**Other apps consume from it:**
- Every app — provides `request.active_company`, `request.user`, `conditional_login_required`, `AppPermission` gates, and context processors

**URL prefix:** `/users/`

#### Release Notes & Acknowledgement

Author-written release notes live in `release_notes/*.md` as YAML-frontmatter +
markdown files. The `import_release_notes` management command (run from
`startup.sh` on deploy) reconciles them into `ReleaseNote` rows. Per-user
acknowledgements are recorded in `ReleaseNoteAcknowledgement` with timestamp
and IP. `ReleaseNoteGateMiddleware` (in `STATZWeb/middleware.py`) attaches
unacknowledged notes to every authenticated request; `base_template.html`
renders a blocking modal when any exist. Users can browse the archive at
`/whats-new/`. New users only see notes with `publish_date >= date_joined`.
File format and validation rules are in `release_notes/README-rn.md`.

**Shared infrastructure provided to the whole project:**
- `STATZWeb/middleware.py` `LoginRequiredMiddleware` — enforces auth globally; respects `settings.REQUIRE_LOGIN`
- `STATZWeb/middleware.py` `ReleaseNoteGateMiddleware` — sets `request.unacknowledged_release_notes` for the release-notes modal
- `users/middleware.py` — injects `request.active_company` on every request
- `users/context_processors.py` — injects `user_preferences`, `active_company`, `system_messages`
- `contracts/context_processors.py` — injects reminder sidebar data (scoped by `active_company`)
- `STATZWeb.decorators.conditional_login_required` — per-view auth enforcement

#### Session Timeout & Lock Screen
- **New URL:** `users/session/keep-alive/` (name: `session-keep-alive`), POST, login required, renews session, returns `{"status": "ok", "expires_in": N}`
- **New static asset:** `static/js/session_timeout.js` — inactivity tracker, warning modal, lock screen overlay; exposes `window.sessionTimeout.isUserActive()`
- **Context Processor (`STATZWeb/context_processors.py`):** `version_context` now injects `session_cookie_age` for authenticated users
- **Template Integration (`base_template.html`):** Injects `window.STATZ_SESSION_MAX_AGE`, `STATZ_KEEPALIVE_URL`, `STATZ_LOGIN_URL`, `STATZ_LOGOUT_URL`, and `STATZ_CSRF_TOKEN` for authenticated users
- **Message Polling:** The unread message poller in `base_template.html` now checks `window.sessionTimeout.isUserActive()` and pauses automatically after 15 minutes of inactivity

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
[training], [accesslog], [inventory], [tools] ── fully isolated
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
| Background task registry | `core.ScheduledTask` + `core/management/commands/run_background_tasks.py` | `sales/tasks/`, other app task modules |
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
| `ContractLevelCharge` | `contracts` | `Contract` FK; copied from `ProcessContractCharge` at finalization |
| `ProcessContractCharge` | `processing` | `ProcessContract` FK; staging model |
| `Solicitation` | `sales` | `SolicitationLine`, `SupplierRFQ`, `GovernmentBid` |
| `ReportRequest` | `reports` | Nothing downstream |
| `OpenRouterModelSetting` | `suppliers` | `suppliers` enrichment views, `reports` AI stream endpoint |

---

## Azure Telemetry & Infrastructure

- **Application Insights Integration:** Integrated via `opencensus-ext-azure`.
- **Environment & Activation:** Enabled only in production (`IS_PRODUCTION=True`) when the `APPLICATIONINSIGHTS_CONNECTION_STRING` environment variable is present.
- **Data Captured:**
  - HTTP Request Traces (100% sample rate via `OpencensusMiddleware`).
  - Unhandled Exceptions.
  - Django Log Forwarding: Forwarding of all `WARNING` level and higher logs from the major loggers (`django`, `STATZWeb`, `users`, `contracts`, `processing`).
- **Resource Information:** Azure GCC High Application Insights resource located in USGov Virginia, resource group `StatzWeb-App`. The connection string is auto-injected by Azure under the environment variable `APPLICATIONINSIGHTS_CONNECTION_STRING`.

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
Add a callable under the owning app's `tasks/` package, register it in `TASK_FUNCTIONS` in `core/management/commands/run_background_tasks.py`, and insert a `ScheduledTask` row (data migration or Django admin) with `name`, `interval_minutes`, and `run_order`. Do not add ad-hoc management commands for recurring work.

### When adding a field that needs audit history
Add the field path to `transactions/signals.py` `TRACKED` dict. Never use `QuerySet.update()` on tracked models — it bypasses save signals.

### When renaming a URL name used outside its app
Run repo-wide search before changing. `training:dashboard` is hardcoded in `base_template.html`. `transactions` modal uses hardcoded `/transactions/...` paths. `reports` admin JS posts to `suppliers:global_ai_model_config`.

---

## CSS Architecture (All Apps)

No Tailwind. Bootstrap 5 plus three global CSS files:

- `static/css/theme-vars.css` — brand tokens for header and sidebar (`--company-primary`, `--company-secondary`, `--header-height`) plus authoritative light-mode text color overrides (`--bs-body-color`, `--bs-secondary-color`, `--bs-tertiary-color`, table/nav-link tokens). Light-mode body text was darkened to `#1a1a1a` for readability; Gov Actions/Log Fields secondary text uses the same tokens plus scoped overrides for legacy `text-gray-*` classes. Spacelab Bootstrap 5.3 handles remaining theming. Do not add dark-mode text tokens here.
- `static/css/app-core.css` — all layout, component, button, and modal styles. New named classes go here.
- `static/css/utilities.css` — utility and helper classes.

Cache-busting: all CSS `<link>` tags use `?v={{ cache_version }}` which is injected by `STATZWeb.context_processors.cache_version_context`. The service worker cache name is also versioned with the same value. Both are sourced from `WEBSITE_DEPLOYMENT_ID` on Azure.

When editing any template: replace Tailwind utility classes with Bootstrap 5 equivalents or named classes from `app-core.css`. Do not leave Tailwind classes in place. Button pattern: `.btn-outline-brand` (standard) and `.btn-outline-brand.btn-tinted` (pill with `#eff6ff` tint).


## Release Notes (Changelog) Rules

Product release notes are file-based. The markdown files are the **source of truth** (the DB is just a cache). When generating a release note, you MUST adhere to these strict validation rules, or the system will skip the file on deployment.

- **File Path & Naming:** `release_notes/YYYY-MM-DD-short-slug.md`
- **Body:** Must be valid Markdown and non-empty. 
- **Frontmatter (Required):** You must include a YAML frontmatter block exactly like this:

```yaml
---
id: 2026-05-11-short-slug      # CRITICAL: Must exactly match the filename stem (without .md)
title: Human-readable title
published: false               # Always default to false on dev branches; set true when ready to ship
publish_date: 2026-05-11       # Must be an ISO date
tags: [improved, contracts]    # CRITICAL: Must be a list of EXACTLY TWO strings (see taxonomy below)
critical: false                # Must be a boolean
---

```

**Strict Tag Taxonomy:**
The `tags` array will fail validation if it does not contain exactly two items:

1. **One Change Type:** `new`, `improved`, `fixed`, OR `breaking`
2. **One Area:** `contracts`, `finance`, `sales`, `training`, OR `system`
*(Do not invent new tags. Unknown tags cause the file to be skipped.)*

```

---

## Anthropic API Budget Tracker
- Model: `core.APIBudget` (singleton, pk=1) tracks estimated running balance. `core.APIUsageLog` logs every call with model, tokens, cost, and call site.
- Central wrapper: `core.anthropic_client.call_anthropic(payload, call_site)` — all Anthropic API calls must route through this.
- Pricing constants in `core/anthropic_client.py` — update `MODEL_PRICING` when adding new models.
- Context processor `core.context_processors.api_budget` injects `api_budget` and `api_budget_calls_today` into superuser requests only.
- Budget card partial: `core/templates/core/partials/api_budget_card.html` — included on Intake Queue, Processing Queue, Reports hub, and Index pages inside `{% if request.user.is_superuser %}`.
- Sync URL: `core:sync_api_budget` (POST) — superuser only, sets balance to match Anthropic console.

---

## Progressive Web App (PWA)
- **Edge PWA Compatibility:**
  - Added `display_override` configuration (`["window-controls-overlay", "standalone", "minimal-ui"]`) in `static/manifest.json` to keep internal navigations in the standalone Edge PWA window.
  - Corrected navigation links in `contract_lifecycle_dashboard.html` by removing `target="_blank"` and `rel="noopener"` from metrics links, ensuring they navigate within the same PWA window.
  - Updated the service worker in `templates/sw.js` to explicitly claim and handle navigation fetch events (`event.request.mode === 'navigate'`), preventing the browser from opening new window tabs for page navigations.
  - PWA users must reinstall the application after manifest updates for the changes to take full effect.


---

## Completed migrations and fixes

- **Migration 0061 MSSQL deadlock fix (v2):** Root cause was `.iterator()` holding an open server-side cursor while INSERT commands fired on the same pyodbc connection. Fix: materialize contracts via `list(queryset.values(...))` before any writes, then `bulk_create` in batches of 500 inside a single atomic block.
- **Migration 0052 MSSQL deadlock fix:** Root cause was `Contract.objects.iterator()` holding an open server-side cursor while `DibbsAwardMod.objects.get()` fired on the same pyodbc connection. Fix: materialize unmatched mods and contracts via `list(...)` / pre-built dicts before any secondary DB reads or writes, then `bulk_update` in batches of 500 inside a single atomic block. Idempotent on retry (`matched_contract__isnull=True` filter + skip already-set FKs).

---

## Recently completed features

Partner Commission Reconciliation: Upload a partner's Excel commission
report and reconcile against ClinSplit records. Supports PPI's 3-tab format
(TO BE PAID / PAID TO MSC / MISSING INFORMATION). Service layer in
contracts/services/partner_reconciliation.py is adapter-based for future
partner formats. Models: PartnerReconciliation, PartnerReconciliationRow
in contracts app. URLs at /contracts/partner-reconciliation/.
Four status types: match, amount_discrepancy, payment_discrepancy,
missing_in_statz, missing_in_partner.



