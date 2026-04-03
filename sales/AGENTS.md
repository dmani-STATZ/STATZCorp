# AGENTS.md — `sales` App

## 1. Purpose of This File

This file defines safe-edit guidance for the `sales` Django app for AI coding agents and future developers. It is not a repeat of `CONTEXT.md` — read `sales/CONTEXT.md` first for domain context and the `DIBBS_System_Spec` for intent and vision, then use this file when making code changes.

---

## 2. App Scope

**Owns:** The entire DIBBS bidding lifecycle — file import, solicitation triage, supplier matching, RFQ dispatch, quote entry, government bid assembly, BQ file export, and DIBBS AW file award import (`DibbsAward`).

**Owns operationally:** `ImportBatch`, `ImportJob`, `Solicitation`, `SolicitationLine`, `ApprovedSource`, `SupplierNSN`, `SupplierFSC`, `SupplierMatch`, `SupplierRFQ`, `SupplierContactLog`, `SupplierQuote`, `GovernmentBid`, `CompanyCAGE`, `EmailTemplate`, `DibbsAward`, `AwardImportBatch`, `NoQuoteCAGE`, `InboxMessage`, `InboxMessageRFQLink`.

**Does not own:** `suppliers.Supplier` — this is the central supplier record from the `suppliers` app. Every FK to a supplier crosses app boundaries.

**Does not own:** Authentication (`auth.User`), contracts data (`contracts.models.Clin` is read for NSN backfill only).

**App type:** Core domain app. This is the operational heart of the product. It is tightly coupled internally and fragile in the import → match → RFQ → bid status pipeline.

---

## 3. Read This Before Editing

- **Azure App Service environments are ephemeral.** Always **discover the Python path dynamically** in shell scripts (e.g. resolve `PYTHON_EXE` from the Oryx `antenv` layout) rather than calling raw `python` or assuming a fixed `/tmp/antenv` path. Fixed paths after platform recycle or image updates can cause **container crash loops**.

### Performance — Azure / container startup

- **Oryx handles `collectstatic` during deployment build.** Redundant `collectstatic` invocations in **`startup.sh`** must be avoided so cold starts stay **under ~2 minutes** (repeat static collection previously contributed to **~10-minute** startups and health-check timeouts).
- **Never run full binary installations (like Playwright) in `startup.sh` without first checking for existing files.** Unconditional `playwright install` on every container start significantly delays availability; gate on the presence of cached driver/browser paths (or install during the build image/Oryx phase instead).

### Before changing models
- Read the relevant `sales/models/*.py` file.
- Check `sales/migrations/` for the highest migration and existing constraints (includes `NoQuoteCAGE` / `0018_no_quote_cage` or later).
- Search templates under `sales/templates/sales/` for field references — many field names appear in templates directly.
- Check `sales/services/bq_export.py` for `COMPANY_FILLED_COLUMNS` — it maps 1-based BQ column indices to exact model field names on `GovernmentBid` and `CompanyCAGE`.
- Check `sales/services/importer.py` for chunking constants (`SOLICITATION_CHUNK=200`, `LINE_CHUNK=230`, `AS_CHUNK=400`) and any field references in upsert logic.
- Check `sales/services/matching.py` — references `SupplierMatch.match_method`, `SupplierNSN.nsn`, `SupplierFSC.fsc_code`, `ApprovedSource.approved_cage` by name.

### Before changing views
- Read the full view module being changed (`sales/views/*.py`).
- `sales/views/awards.py` — upload enforces `request.user.is_staff`; do not remove that check. The result view pops `aw_import_result` from the session — do not change the session key name.
- Check `sales/urls.py` for the URL name being used — several names are duplicated (e.g., `bids/` and `bids/ready/` both point to `bids_ready`; `rfq/` and `rfq/pending/` both point to `rfq_pending`).
- Check templates for context variable names — the solicitation **workbench** (`solicitation_workbench` / `detail.html`) passes `solicitation`, `line`, `supplier_matches`, `procurement_history`, `packaging`, `has_pdf_blob` (enables workbench Re-parse controls), `prev_sol`, `next_sol`, `nav_record_num`, `nav_total`, `list_qs`, `queued_rfq_count`, `workbench_claim_blocked`, `show_triage_actions`, and related keys; do not assume the old tabbed matches/rfq/bid context unless reintroduced. **`NsnProcurementHistory`** is unique on `(nsn, contract_number)`; `save_procurement_history()` inserts new rows via raw `executemany` (`%s`) and chunked `UPDATE` for existing keys — never overwrite price/qty on updates; only refresh `last_seen_sol` / `extracted_at`.
- Check `sales/context_processors.py` — adds `overdue_rfq_count` to every request.

### Before changing services
- `sales/services/bq_export.py` — any rename of `GovernmentBid` or `CompanyCAGE` fields listed in `COMPANY_FILLED_COLUMNS` will silently produce wrong BQ output (no attribute error, wrong column filled).
- `sales/services/matching.py` — the three tiers are interdependent; changing tier boundaries or deduplication logic affects bid quality downstream.
- `sales/services/email.py` — `_default_cage()` must always find exactly one `CompanyCAGE(is_default=True, is_active=True)`. If that invariant breaks, every RFQ email fails.
- `sales/services/importer.py` — step results stored in `ImportJob.step_results` as JSON must include `batch_id` and `import_date`; the progress template reads those keys by name.
- `_run_lifecycle_sweep()` in `services/importer.py` runs at the start of every import inside `transaction.atomic()` (parse step in `imports.py`, and the legacy `run_import()` entry point). It transitions `New → Active` for prior-batch records and `→ Archived` for expired eligible records using **per-pass `QuerySet.update()`** (not chunked `bulk_update`) to avoid SQLite write-lock storms. **`NO_BID` is excluded** from the expired→Archived sweep — passed solicitations stay `NO_BID` permanently and appear under **Closed Solicitations** (`solicitation_closed`) / No-Bid tab. It must remain the first database write in the parse-step `try` block (before `create_import_batch`) and the first operation inside `run_import()`'s lifecycle `atomic` block. Do not move it after batch creation or call it conditionally.
- `sales/services/graph_inbox.py` — uses the same MSAL client credentials pattern as `graph_mail.py`. GCC High endpoints only. `INBOX_FETCH_LIMIT=50` is hardcoded — change with care as large fetches will slow inbox load. Body is fetched lazily per message open, not in bulk.

### Before changing templates
- `sales/templates/sales/rfq/partials/mailto_buttons.html` — referenced from the RFQ pending view (solicitation detail Matches tab uses queue buttons + No Quote modals, not this partial).
- `sales/templates/sales/import/progress.html` — reads `step_results` JSON keys by name; must stay in sync with `_save_step` in `sales/views/imports.py`.
- `sales/templates/sales/bids/builder.html` — contains inline form field names tied to `GovernmentBid` fields; mismatch causes silent wrong saves.
- Check `sales/base.html` nav links before renaming any URL name.

### Before changing forms
- `ImportUploadForm` (`sales/forms.py`) is shared between `import_upload` and `import_fetch_dibbs` — changes affect both entry points.
- `QuoteEntryForm` is defined inside `sales/views/rfq.py` (not `forms.py`) — search there, not in `forms.py`.

---

## 4. Local Architecture / Change Patterns

**Business logic location:** Services (`sales/services/`). Views should orchestrate services, not contain logic. Do not add parsing, matching, or export logic directly into views.

**Validation:** Split across two patterns:
- `QuoteEntryForm` (inside `views/rfq.py`) — form-based Django validation.
- `bid_builder` view — manual sanitization and recalculation inline in the view function. There is no service layer for bid validation other than `bq_export.validate_bid_for_export`.

**Templates:** Server-rendered with minimal JS. The RFQ center (`rfq/center.html`) is AJAX-driven via fetch calls; its partial (`rfq/partials/center_panel.html`) is returned as HTML fragment. Most other views are full-page server renders.

**Status transitions:** Solicitation status is advanced explicitly in service calls (e.g., `send_rfq_email` advances to `RFQ_SENT`, quote entry advances to `QUOTING`). There are no signals or model-level `save()` hooks triggering transitions. Status flow must be managed manually wherever status changes occur.

**Admin:** `sales/admin.py` registers nothing. All staff actions go through custom views. Do not assume Django admin works for any sales model.

**Background processing:** Azure WebJobs run `scrape_awards`, `auto_import_dibbs`, and optionally `fetch_pending_pdfs` (deprecated as a 5‑minute default; use for manual/queue catch-up). **`auto_import_dibbs`** is a **three-phase** nightly job: **Loop A** — missing DIBBS dates → `fetch_dibbs_archive_files` (IN + BQ zip only; AS inside zip) + `run_import()`. **Loop B** — set-aside sols (`small_business_set_aside != 'N'`) with no `pdf_blob`, fetch PDFs in **batches of 10**, **one Playwright session per batch** (full browser restart between batches for connection hygiene). **Loop C** — after all B sessions close, `parse_pdf_data_backlog()` parses every sol with a blob and null `pdf_data_pulled` (procurement history + packaging; `pdf_data_pulled` always set). `fetch_pending_pdfs` mirrors the batch-of-10 fetch pattern for PENDING/FAILED queue sols, then runs the same parse backlog. The interactive import pipeline runs via four sequential AJAX HTTP POSTs, not an internal task queue.

---

## 5. Files That Commonly Need to Change Together

### Adding a new field to `GovernmentBid`
→ `sales/models/bids.py` + new migration + `sales/services/bq_export.py` (if it maps to a BQ column) + `sales/templates/sales/bids/builder.html` + `sales/views/bids.py` (bid_builder POST handling)

### Adding a new solicitation status
→ `sales/models/solicitations.py` (STATUS_CHOICES) + every view that checks that status string + `sales/templates/sales/solicitations/list.html` (filter dropdown) + `sales/templates/sales/solicitations/detail.html` (pipeline ribbon **and** status banner block for non–New/Matching statuses) + `sales/context_processors.py` if it affects overdue count logic

### Changing solicitation list tabs, filters, sort, or NO_BID visibility
→ `sales/views/solicitations.py` — keep `_list_qs_before_tab`, `_apply_list_tab_filter`, `_apply_list_sort`, and `_build_list_queryset` aligned with `solicitation_list()` so detail **Prev/Next** (`?list_qs=`) matches the list (including `tab=research` Research Pool and `sol_mass_pass` `filter_qs` replay). Update `sales/templates/sales/solicitations/list.html` (tabs, tab counts, **Pass All in This View**, **Mass Pass History** link, `filter_snapshot` on row links) as needed.

### Adding a new match tier or method
→ `sales/services/matching.py` + `sales/models/matching.py` (MATCH_METHOD_CHOICES) + new migration + `sales/templates/sales/solicitations/detail.html` (matches tab) + `sales/templates/sales/rfq/partials/mailto_buttons.html`

### Changing `CompanyCAGE` fields
→ `sales/models/cages.py` + new migration + `sales/services/bq_export.py` (check `COMPANY_FILLED_COLUMNS`) + `sales/services/email.py` (`_default_cage()` and `_rfq_body()`) + `sales/views/settings.py` (cage add/edit form handling) + `sales/templates/sales/settings/cage_form.html` (RFQ inbox reads the shared mailbox via Graph env vars — not CAGE fields)

### Changing `EmailTemplate` fields
→ `sales/models/email_templates.py` + new migration + `sales/services/email.py` (template rendering) + `sales/views/settings.py` + `sales/templates/sales/settings/email_template_form.html` + `sales/templates/sales/settings/email_templates.html`

### Adding a new import AJAX step
→ `sales/urls.py` + `sales/views/imports.py` + `sales/templates/sales/import/progress.html` (step checklist) + `sales/services/importer.py` if new service logic needed

### Changing `SupplierNSN` or `SupplierFSC` fields
→ `sales/models/suppliers.py` + new migration + `sales/services/matching.py` + `sales/views/suppliers.py` + `sales/templates/sales/suppliers/detail.html`

### Flagging or restoring a No Quote CAGE
→ `sales/models/no_quote.py` + migration + `sales/services/no_quote.py` + `sales/views/suppliers.py` + `sales/views/entity_lookup.py` + `sales/views/settings.py` + `sales/views/solicitations.py` + `sales/views/rfq.py` (batch send, queue add/send, `supplier_create_and_queue`) + `sales/templates/sales/suppliers/detail.html` + `sales/entity_lookup.html` + `sales/templates/sales/solicitations/detail.html` + `sales/templates/sales/rfq/pending.html` + `sales/base.html` / `sales/settings/cages.html` nav

### Adding a new page to an existing section (RFQ Center, Bid Center, or Settings)
→ `sales/views/<module>.py` — add `'section': '<value>'` to the new view's context
→ `sales/base.html` — add the new sub-nav link to the correct `{% if section == '...' %}` block
→ `sales/urls.py` — add the URL pattern as usual
→ Update the active detection `or` chain in the sub-nav block to include the new url_name

### Changing inbox claim expiry duration
→ `sales/models/inbox.py` — `claim_for()` method timedelta value
→ `CONTEXT.md` — update the 20-minute reference
→ `AGENTS.md` — update this entry

---

## 6. Cross-App Dependency Warnings

### This app depends on:
- **`suppliers.Supplier`** (table: `contracts_supplier`) — every SupplierMatch, SupplierRFQ, SupplierQuote, SupplierContactLog, SupplierNSN, SupplierFSC, and GovernmentBid references it. Renaming or restructuring `Supplier` fields (`contact`, `primary_email`, `business_email`, `name`, `cage_code`) breaks `sales/services/email.py` (`_supplier_email()`), supplier list/detail views, and RFQ send flows.
- **`contracts.models.Clin`** — read in `sales/services/matching.py::backfill_nsn_from_contracts()`. If `Clin` fields change (especially nsn, supplier FK), this function breaks silently.
- **`auth.User`** — referenced as FK in `SupplierRFQ.sent_by`, `SupplierContactLog.logged_by`, `SupplierQuote.entered_by`, `EmailTemplate.created_by`. If `AUTH_USER_MODEL` changes or user fields are restructured, update these models.
- **`settings.DEFAULT_FROM_EMAIL`** — used in `sales/services/email.py` for outbound email sender.
- **`settings.SAM_API_KEY`** — required by `sam_entity.py` for CAGE lookup; missing values cause graceful degradation (entity lookup errors shown to user).
- **`SAMEntityCache` (`dibbs_sam_entity_cache`)** — CAGE lookup cache (30-day TTL, filled via **`get_or_fetch_cage()`** on demand). Do **not** call `get_or_fetch_cage()` from inside Playwright / `sync_playwright()` blocks (same ORM boundary as scrapers: mssql driver vs. browser event loop). Keep cache ORM access in HTTP views or other code that runs only after the browser session has fully exited.
- **Workbench Approved Sources — SAM display names:** The workbench sidebar shows cached SAM entity names for CAGE rows **without** a `contracts_supplier` match using **`SAMEntityCache` only** (`sam_cache_map` from `_workbench_sidebar_context`). Do **not** add SAM HTTP/API calls to `solicitation_workbench` or sidebar context builders; if no cache row exists, the UI shows a dash until the user opens **Look Up** (entity lookup page in a new tab), which populates the cache.

### Other apps that depend on this app:
- **`STATZWeb/settings.py`** — registers `sales.context_processors.rfq_counts` in `CONTEXT_PROCESSORS`. If this processor is renamed or its module path changes, the setting must be updated or a 500 error occurs on every page load.
- No other apps are known to import from `sales` directly. Run `grep -r "from sales" .` and `grep -r "import sales" .` to verify before refactoring public surfaces.

### URL namespace:
- The `sales:` namespace is used in templates across the app. Before renaming any URL name in `sales/urls.py`, search all templates under `sales/templates/` for `{% url 'sales:<name>' %}`.

---

## 7. Security / Permissions Rules

- **Every view must retain `@login_required`**. This app handles sensitive procurement data (solicitation numbers, supplier pricing, bid data). Do not remove or weaken auth decorators.
- **Staff-only endpoints:** `backfill_nsn` uses `@user_passes_test(lambda u: u.is_authenticated and u.is_staff)`. `awards_import_upload` checks `request.user.is_staff`. `no_quote_list` and `no_quote_deactivate` require `is_staff`. Do not remove these checks or widen access.
- **SAM debug JSON** in `sales/templates/sales/entity_lookup.html` is conditionally shown only to staff (`{% if request.user.is_staff %}`). Do not remove this guard.
- **Import batch delete** (`import_batch_delete`) only deletes solicitations with `status='New'`. This guard prevents accidental deletion of in-progress work. Do not relax this filter.
- **`sol_mass_pass`** (`POST /solicitations/mass-pass/`) performs bulk No-Bid updates. With `mass_pass_all=1` it rebuilds the list queryset from posted `filter_qs` and runs a single `QuerySet.update(status='NO_BID')` restricted to `New` and `Active` only (never RFQ_SENT, QUOTING, etc.), excluding rows with `QUEUED` RFQs. The `sol_ids` path is page-scoped with the same status filter. Do not widen these guards — they prevent accidental loss of in-flight RFQ/bid work. **Before** that `update()`, the view snapshots every affected row’s prior status into **`MassPassLog`** (`dibbs_mass_pass_log`) so **`mass_pass_undo`** can restore rows that are still `NO_BID` back to **`Active`** (one undo per log; chunked `id__in` queries). **Do not remove the snapshot / `MassPassLog.objects.create` step from `sol_mass_pass`** — it is required for undo functionality.
- **File uploads** (IN/BQ/AS files) are saved to temp directories and removed during the match step. Do not change temp file handling without verifying cleanup still occurs.
- **RFQ mailto flows** generate `mailto:` URLs rather than sending email automatically. This is intentional — `rfq_mark_sent` requires the human to confirm the email was sent. Do not change this to auto-send without understanding the workflow.
- **`SupplierContactLog`** provides an audit trail for all RFQ communications. Do not remove or bypass log creation in `send_rfq_email` or `rfq_mark_sent`.

---

## 8. Model and Schema Change Rules

- **Before renaming any field** on `GovernmentBid` or `CompanyCAGE`, check `sales/services/bq_export.py::COMPANY_FILLED_COLUMNS`. This dict maps BQ column positions to field names using Python `getattr`. A rename will silently export empty/wrong columns with no Python error.
- **Before renaming `SolicitationLine.bq_raw_columns`**, check `sales/services/bq_export.py` — it reads this JSON field to get the 121-column original BQ row for overlay.
- **Before renaming `Solicitation.status` choices**, search all views and templates for hardcoded status strings (`'New'`, `'RFQ_SENT'`, `'BID_SUBMITTED'`, etc.). These appear as raw string comparisons in views and template conditionals.
- **`CompanyCAGE.is_default` invariant:** exactly one active default cage must exist at all times. The `settings_cage_add` and `settings_cage_edit` views enforce this by resetting all other cages to `is_default=False` when a new default is set. Any direct ORM manipulation must maintain this invariant.
- **`EmailTemplate.is_default` invariant:** same one-default constraint enforced in `email_template_set_default`. `sales/services/email.py` calls `EmailTemplate.objects.filter(is_default=True).first()` and fails gracefully if none found, but RFQ emails will have no template content.
- **SMTP credentials** are stored in environment variables (`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`), not on `CompanyCAGE`. Do not add SMTP credential fields to the model. The `smtp_reply_to` field on `CompanyCAGE` holds only the Reply-To address, not auth credentials.
- **Graph Mail credentials** are stored in env vars (`GRAPH_MAIL_TENANT_ID`, `GRAPH_MAIL_CLIENT_ID`, `GRAPH_MAIL_CLIENT_SECRET`). Never hardcode these. `GRAPH_MAIL_ENABLED` is the feature flag — set to `False` to revert to mailto fallback without any code change. Do not add Graph credentials to `CompanyCAGE` or any model.
- **`GRAPH_MAIL_SENDER` is environment-specific and must not be hardcoded.** Production value is `quotes@statzcorp.com` (inherited from Sales Patriot — do not change without sales team sign-off). Dev/test value is `rfq@statzcorp.com`. Never substitute a newly created M365 account — new accounts lack sending reputation and will be flagged as spam by supplier mail servers when sending cold RFQ volumes.
- **`from_email` on outbound mail must equal `EMAIL_HOST_USER`** exactly (via `DEFAULT_FROM_EMAIL`, which is set from that env var). Microsoft 365 rejects sends where the authenticated account and the From address differ.
- **Cross-app FKs:** `SupplierNSN`, `SupplierFSC`, `SupplierMatch`, `SupplierRFQ`, `SupplierContactLog`, `SupplierQuote`, and `GovernmentBid` all have FKs to `suppliers.Supplier`. Changing `on_delete` behavior requires understanding impact on those cascades.
- **`DibbsAward` AW import:** Python stages raw rows into `dibbs_award_staging` using chunked raw `executemany` (`_chunked`, `AW_CHUNK=100`); do not use `bulk_create` for staging inserts (`django-mssql-backend` adds `OUTPUT INSERTED.id` and triggers SQL Server error 8115). Classification, dedup, solicitation matching, faux upgrades/inserts, and `dibbs_award_mod` inserts run in T-SQL in `usp_process_award_staging`. Re-scrapes must remain safe via the proc’s existence checks and table unique constraints — do not reintroduce a monolithic Python `_process_records()` path. Do not add `auto_now_add` / `auto_now` fields to `DibbsAward` unless every write path sets them explicitly. Import timing remains `aw_file_date` and `AwardImportBatch.imported_at`. The OUTPUT INSERTED / `bulk_create` hazard applies app-wide; any new high-volume insert path should prefer raw `executemany` or T-SQL.
- **Staging table contract:** `dibbs_award_staging` is a transient table. Rows are inserted by Python and deleted by `usp_process_award_staging` at the end of each run. The table should be empty between runs. If rows persist after a failed run, they can be safely deleted by `stage_id` in SSMS. `dibbs_award_staging_errors` is permanent — do not truncate it.
- **Stored procedure:** `usp_process_award_staging` lives in `sales/sql/usp_process_award_staging.sql`. Deploy changes via SSMS using `CREATE OR ALTER PROCEDURE`. Never run this file via Django or a management command.
- **`stage_id`:** A UUID generated by Python via `uuid.uuid4()` before staging insert. It is the isolation key — the proc operates only on rows matching `@stage_id`. Two runs can overlap safely.
- **`DibbsAwardMod` dedup contract:** dedup key is `(award, mod_date, nsn, mod_contract_price)` and must remain stable. Import logic should skip only when all four values match.
- **Faux award contract:** `DibbsAward.is_faux=True` rows are placeholders synthesized when MOD rows arrive before original awards. Original-award imports must upgrade matching faux rows (`is_faux=False`) rather than creating duplicates. Faux rows must be excluded from wins/report aggregates.
- **Insert-path contract:** Python uses raw `executemany` for `dibbs_award_staging` only. Production `DibbsAward` / `DibbsAwardMod` rows are inserted by `usp_process_award_staging` in SQL Server. Do not route production award inserts through Django `bulk_create` (same `OUTPUT INSERTED` / error 8115 issue).
- **Migrations:** Run `makemigrations sales` after any model change and review the generated file before applying (schema includes `NoQuoteCAGE` from `0018_no_quote_cage` or later).
- **`WeWonAward` SQL view contract:** `WeWonAward` is an unmanaged model backed by SQL Server view `dibbs_we_won_awards`. The view must be created manually in SSMS and is **not** managed by Django migrations. Do not run `makemigrations` expecting Django to create this view.

---

## 9. View / URL / Template Change Rules

- **URL names must not be renamed casually.** Templates reference them with `{% url 'sales:<name>' %}`. Before renaming, `grep -r "sales:<name>" sales/templates/` and check `sales/base.html` nav links.
- **Duplicate URL patterns exist by design:** `bids/` and `bids/ready/` both route to `bids_ready`; `rfq/` and `rfq/pending/` both route to `rfq_pending`. Do not clean these up without checking if both are in use from nav links or other templates.
- **`rfq/partials/center_panel.html`** is returned as an HTML fragment by `rfq_center_detail`. It must remain a partial (no `{% extends %}`) and its context keys must match what the view passes.
- **`rfq/partials/mailto_buttons.html`** is included from `rfq/pending.html` (solicitation detail Matches tab uses queue UI, not this partial).
- **Section-driven sub-nav contract:** `sales/base.html` renders RFQ/Bid/Settings secondary navigation from `section` context. Full-page renders in `sales/views/rfq.py`, `sales/views/bids.py`, and `sales/views/settings.py` must include `"section"` (`"rfq"`, `"bids"`, `"settings"` respectively) or the correct primary/sub-nav highlight will break.
- **Do not reintroduce per-template RFQ Queue/Inbox tab strips** in `sales/templates/sales/rfq/center.html` or `sales/templates/sales/rfq/inbox.html`; those routes are navigated via the shared sub-nav in `sales/base.html`.
- **`sales/templates/sales/import/upload.html`** — Combines POST `import_fetch_dibbs` (date + submit) and a client-driven manual path that fills hidden `ImportUploadForm` fields and submits `import_upload`. Do not reintroduce SAM awards skip checkboxes or `skip_sam` POST data; awards are loaded only via `/sales/awards/import/`.
- **Import progress page** (`import/progress.html`) drives four steps and reads each step’s JSON response in the browser. `_save_step` in `imports.py` merges into `ImportJob.step_results`; keep keys aligned with the views: parse (`import_date`, `sol_count`, `bq_count`, `as_count`, `parse_errors`, `new_to_active`, `expired_to_archived`), solicitations (`sols_created`, `sols_updated`), lines (`lines_created`, `lines_updated`, `as_loaded`), match (`matches_found`, `tier1`, `tier2`, `tier3`). `ImportJob.batch_id` and `ImportJob.import_date` are set on the job row during the parse step.
- **`global_search` view** returns JSON when `?fmt=json` is present, plain HTML otherwise. The top-bar search in `sales/base.html` calls it with `fmt=json`. Do not remove the format check.
- **Solicitation list ↔ workbench navigation:** The list encodes active filters (except `page`) into `?list_qs=` on each row’s detail link. The primary solicitation screen is `solicitation_workbench` (URL name `solicitation_detail`). It **should** receive `list_qs` whenever the user should have stable **Previous / Next / Record X of Y** that matches list filters and sort; without `list_qs`, prev/next fall back to the Sol Review / Research session queue when applicable, or show a single-record counter. `_build_list_queryset()` must stay aligned with `solicitation_list()`. **PASS** uses `_capture_workbench_list_nav_snapshot()` before setting `NO_BID` so post-action redirects advance to the next list row like **RESEARCH** (after PASS, a rebuilt list queryset often drops the current sol from non–no-bid tabs). **Closed Solicitations** live at `sales:solicitation_closed` (`/sales/solicitations/closed/`); `/solicitations/archive/` is a permanent redirect. `queued_rfq_count` for banners uses `SupplierRFQ` filtered by `line__solicitation` and `status='QUEUED'`. **`solicitation_reparse`** (POST `/solicitations/<sol>/reparse/`) re-runs `parse_procurement_history` + `parse_packaging_data` against stored `pdf_blob`; keep `@login_required` and CSRF expectations aligned with other JSON POSTs.
- **Workbench manual supplier autocomplete:** `rfq_manual_supplier_search` (GET `q` min 2 chars; optional `solicitation_number` / `sol_number` excludes suppliers who already have any `SupplierRFQ` on that solicitation) returns an HTML fragment when `HX-Request` is set (HTMX typeahead target `#wb-manual-results`) or a JSON array `[{id, name, cage}]` otherwise. `rfq_queue_add_manual` stages `SupplierRFQ(QUEUED, sent_by=user)` on the solicitation’s first line, advances `New`/`Active`/`Matching` → `RFQ_PENDING`, and may set `pdf_fetch_status='PENDING'` when `pdf_blob` is empty — it does **not** create `SupplierMatch`. No Quote CAGE → JSON `409` with error `No Quote CAGE`; HTMX errors swap OOB into `#wb-manual-results`. Success (HTMX) returns OOB `innerHTML` for `#wb-matches-sidebar` via `_workbench_sidebar_context` + `workbench_sidebar_matches.html`. Standalone refresh: GET `solicitation_workbench_sidebar_partial`. **`rfq_enter_quote` POST (success):** if no `SupplierMatch` for `(line, supplier)`, create `MANUAL` tier 3 score `0`; then `SupplierNSN.get_or_create` with normalized NSN, `match_score=50`, `source='quote_confirmed'` when the line has an NSN. **`build_consolidated_supplier_list`** supplies `is_manual` and merges RFQ-only suppliers into the sidebar; templates show **Manual** + **In Queue** badges. **`+ Queue`** on the workbench uses `document.body` click delegation so buttons work after HTMX sidebar swaps.
- **Context processor dependency:** `overdue_rfq_count` is available in every template because `sales.context_processors.rfq_counts` is registered in settings. Do not remove `rfq_counts` without updating `STATZWeb/settings.py`.

---

## 10. Forms / Serializers / Input Validation Rules

- **`QuoteEntryForm` is in `sales/views/rfq.py`**, not `sales/forms.py`. This is non-standard. Search there when debugging quote validation issues.
- **`ImportUploadForm`** (`sales/forms.py`) is used by both `import_upload` and `import_fetch_dibbs`. Changes to required fields affect both flows.
- **Bid builder validation** is inline in the `bid_builder` view (POST branch), not in a dedicated form class. `bq_export.validate_bid_for_export()` provides a second validation pass at export time. Validation that passes bid builder but fails `validate_bid_for_export` will let a user save a DRAFT that cannot be exported.
- **NSN normalization:** `supplier_add_nsn` strips hyphens and enforces 13 characters. If this is changed, update `matching.py::_normalize_nsn()` to stay consistent.
- **FSC normalization:** `supplier_add_fsc` enforces exactly 4 uppercase characters. Changing this must stay consistent with `parser.py` FSC field extraction and `matching.py` tier 3 logic.
- **CAGE code length:** 5 characters, enforced in bid builder, bq_export validation, and model `max_length`. Keep all three consistent.

---

## 11. Background Tasks / Signals / Automation Rules

**No signals.** No Celery tasks. No in-app async task queue.

**The solicitation import pipeline is fully synchronous via four sequential AJAX HTTP POSTs:**
1. `import_step_parse` → parse files
2. `import_step_solicitations` → upsert Solicitation rows
3. `import_step_lines` → upsert SolicitationLine + ApprovedSource rows
4. `import_step_match` → run matching engine

Each step updates `ImportJob.status` and `ImportJob.step_results`. The progress page drives these in order. If a step fails, `ImportJob.status` is set to `'error'` and the message is stored in `ImportJob.error_message`.

**Scheduled/background workers in this app:** (1) `scrape_awards` — nightly Azure WebJob. **Default:** inventory dates on DIBBS (`AwdDates.aspx`), sync new dates as `AwardImportBatch` rows with `scrape_status=MISSING`, build a work queue of non-SUCCESS `AUTO_SCRAPE` batches (oldest first), scrape one date per Playwright session. While scraping, `on_page_complete` only appends rows to an in-memory list; after the browser closes, `awards_file_importer.import_aw_records()` runs **once** with all rows. Then run the expiry notification check. **`--date YYYY-MM-DD`** skips reconciliation and scrapes one date. **`--dry-run`** prints the queue without scraping. It writes into `DibbsAward` via `sales/services/dibbs_awards_scraper.py` and `awards_file_importer.import_aw_records()`. (2) `auto_import_dibbs` — **Loop A:** dates missing `ImportBatch` → `fetch_dibbs_archive_files()` (IN + BQ zip; AS extracted from zip; no CA zip) + `run_import()`. **Loop B:** set-aside sols missing `pdf_blob` → `fetch_pdfs_for_sols()` in **batches of 10** (one Playwright session per batch; ORM updates only after each session exits). **Loop C:** `parse_pdf_data_backlog()` — ORM-only parse for all sols with blob + null `pdf_data_pulled`; `save_procurement_history` uses raw `executemany` inserts. Fifth failed fetch sets `pdf_data_pulled` to cap retries. Does not touch the AJAX stepper or `ImportJob`. Stale import banner when latest `ImportBatch` is >1 day old. `AWARDS_ALERT_EMAIL` alerts for Loop A failures only (not per-PDF misses).

**Scraper ORM rule:** Django ORM calls CANNOT be made inside a `with sync_playwright()` block when running on Azure App Service with mssql backend. The mssql driver's `sql_server_version` cached property opens a `temporary_connection()` which raises `SynchronousOnlyOperation` inside Playwright's event loop. All DB reads and writes must happen only after the `with sync_playwright()` block has fully exited.

**Awards scraper — `on_page_complete`:** The `on_page_complete` callback in `scrape_awards_for_date()` must NEVER touch the database — not even `transaction.atomic()`. The callback may only manipulate Python objects in memory. All database writes for scraped records must happen after `scrape_awards_for_date()` returns and the `with sync_playwright()` block has fully exited.

**Scraper service contract:** `scrape_awards_for_date(award_date, batch_id, on_page_complete, activity_log=None)` scrapes ONE date, calls `on_page_complete(records, page_num, total_pages)` after each page with plain dict rows only (no ORM), optional `activity_log` for stdout milestones (WebJob visibility), and returns a result dict. It has no loop logic, no reconciliation logic, and no DB writes — all of that is the management command's job.

**Awards danger zone:** Non-SUCCESS `AwardImportBatch` records where `today - scrape_date >= 38 days` trigger email (Graph, `AWARDS_ALERT_EMAIL`) + UI warning on the awards import page. DIBBS keeps ~45 days of award data.

**Awards job failure email:** If `GRAPH_MAIL_ENABLED` and `AWARDS_ALERT_EMAIL` are set, any `scrape_awards` run that exits with failure (invalid `--date`, Playwright missing, or at least one scrape date ending `FAILED`) sends one consolidated alert to `AWARDS_ALERT_EMAIL` before `sys.exit(1)`.

**Awards data** is loaded by that scraper (reconciliation or `--date`), with staff AW file upload (`awards_import_upload` / `import_aw_file`) as a fallback. `AwardImportBatch` distinguishes paths via `source` (`FILE_UPLOAD` vs `AUTO_SCRAPE`) and, for scrapes, tracks `scrape_date`, `expected_rows`, `scrape_status`, `last_attempted_at`, and `pages_scraped`.

**Awards grid parsing note:** DIBBS appends a small `»` + package-view link in table cells. `parse_awards_table` uses uniform `get_text(separator=" ", strip=True)` per cell; `normalize_award_record_for_importer` strips `»` and trailing link text with `re.sub(r"\s*».*$", "", v)`. Do not reintroduce per-column anchor surgery.

**`awards_file_importer.py`** exposes `import_aw_file()` (file upload) and `import_aw_records()` (scraper, called once per date after the browser closes). Both stage rows and call `usp_process_award_staging`; business logic lives in SQL Server. Win detection for display and reporting uses the `WeWonAward` SQL view (`dibbs_we_won_awards`), not the `DibbsAward.we_won` column at import time.

**DIBBS fetch** (`import_fetch_dibbs`) requires Playwright + Chromium. If not installed, it will raise `DibbsFetchError`. The awards scraper has the same Playwright dependency.

---

## 12. Testing and Verification Expectations

**There are no automated tests.** `sales/tests.py` contains only the default Django stub.

After any change, manually verify these flows:

| Change area | Verify manually |
|---|---|
| Import pipeline | Upload IN/BQ/AS files, step through progress page, confirm batch and solicitation counts |
| Matching logic | Check solicitation detail → matches tab for expected suppliers and tiers |
| RFQ send | Click mailto button, confirm `rfq_mark_sent` creates `SupplierRFQ` and `SupplierContactLog` |
| Quote entry | Open `rfq/<id>/quote/`, submit a quote, confirm `SupplierQuote` created and solicitation moves to QUOTING |
| Bid builder | Open `bids/<sol_number>/build/`, save draft, mark ready, confirm `GovernmentBid` created |
| BQ export | Open `bids/export/`, select bids, download file, open CSV and verify column 6 = quoter CAGE |
| CompanyCAGE default | Edit settings, set a new default, confirm only one cage has `is_default=True` |
| Email template | Set a template as default, trigger an RFQ, confirm template content appears in mailto body |
| Status context badge | Verify `overdue_rfq_count` badge appears correctly in nav after sending an RFQ with an expired return date |
| Solicitation list / detail nav | Open list with filters and sort; open a row; confirm Back/Prev/Next and status banners; confirm No-Bid tab only shows `NO_BID` and other tabs exclude it |
| Mass pass log / undo | Run **Pass All** or **Pass Selected**, open **Mass Pass History**, confirm log row; **Undo** restores only rows still `NO_BID` to `Active`; workbench **Restore to Active** on a single `NO_BID` sol |

**High-risk files to test after any change:** `sales/services/bq_export.py`, `sales/services/matching.py`, `sales/services/importer.py`, `sales/views/rfq.py`, `sales/views/bids.py`.

---

## 13. Known Footguns

1. **`COMPANY_FILLED_COLUMNS` silent failures.** Renaming any field on `GovernmentBid` or `CompanyCAGE` that appears in the `bq_export.py` mapping will not raise an exception — `getattr` returns an empty string or `None`, and the exported BQ file will quietly contain wrong data.

2. **`_default_cage()` single point of failure.** Every RFQ email and every BQ export depends on exactly one `CompanyCAGE(is_default=True, is_active=True)` existing. Deleting or deactivating that record without setting a new default causes all email and export operations to fail at runtime.

3. **Hardcoded status strings.** Solicitation status values like `'New'`, `'RFQ_SENT'`, `'BID_SUBMITTED'` appear as raw strings in views, templates, and services — not imported from a constants module. Renaming a choice value in `STATUS_CHOICES` without a global search-and-replace will break filters, transitions, and template conditionals silently.

4. **`QuoteEntryForm` not in `forms.py`.** It is defined inline in `sales/views/rfq.py`. Searching `forms.py` for quote validation will find nothing.

5. **`rfq/partials/mailto_buttons.html` is used on RFQ pending.** The solicitation detail Matches tab does not include it; queue + No Quote UI lives inline in `solicitations/detail.html`.

6. **`step_results` JSON keys are implicit contracts.** The import progress page consumes each step’s JSON response in the browser; `_save_step` also merges keys into `ImportJob.step_results`. Renaming or dropping keys (e.g., `sols_created` / `matches_found`) without updating both the view and `progress.html` will silently show blanks or break idempotent step retries.

7. **`item_type_indicator == '2'` skips NSN matching.** In `matching.py`, lines with `item_type_indicator='2'` skip tiers 1 and 2 and go straight to FSC (tier 3) or manual match. This behavior is implicit in the code; adding a tier without accounting for this indicator will apply it to wrong line types.

8. **Playwright dependency with no fallback.** `import_fetch_dibbs` fails completely if Playwright/Chromium is not installed. The error is surfaced to the user as a `DibbsFetchError`, but there is no indication in the UI that it requires a browser binary.

9. **`import_batch_delete` only removes `status='New'` solicitations.** This is intentional but could confuse an agent expecting full batch cleanup. Solicitations that have been triaged, matched, or bid will remain even after the batch is deleted.

10. **`bq_raw_columns` null causes `BQExportError`.** If a `SolicitationLine.bq_raw_columns` is `None` or empty (e.g., from a hand-created line or a migration gap), export will raise `BQExportError` with no easy recovery path.

11. **`_build_list_queryset` vs `solicitation_list` drift.** If list filters or ordering change in one place but not the other, users see wrong Prev/Next order or missing neighbors. Treat `_list_qs_before_tab`, `_apply_list_tab_filter`, and `_apply_list_sort` as part of the same contract as the list template’s `filter_snapshot`.

12. **`get_no_quote_cage_set()` is fetched once per page load.** The set is built at render time for solicitation detail and RFQ pending, not per row. If a CAGE is flagged in another tab, an already-open detail page will not show the badge until refresh — expected.

13. **`GRAPH_MAIL_ENABLED=True` without admin consent causes silent failures.** If the Azure App Registration does not have tenant-wide admin consent granted for `Mail.Send`, Graph will return HTTP 403. The queue send will log the error and return `success=False`. No RFQs will be marked SENT. Check server logs if sends appear to succeed in the UI but emails are not received. Additionally, graph_mail.py uses GCC High endpoints (login.microsoftonline.us, graph.microsoft.us). Do not change these to .com equivalents — this tenant is Azure Government, not commercial Azure.

14. **Wrong `GRAPH_MAIL_SENDER` in production will break supplier relationships.** If `GRAPH_MAIL_SENDER` is set to anything other than `quotes@statzcorp.com` in production, RFQs will arrive from an unrecognized address. Suppliers who have been receiving RFQs from `quotes@statzcorp.com` via Sales Patriot for years may ignore or spam-flag emails from an unknown sender. The production env var in Azure App Service must always be `quotes@statzcorp.com`. The dev `.env` uses `rfq@statzcorp.com` to protect the production mailbox from test traffic.

15. **`graph_inbox.py` requires `Mail.Read` not just `Mail.Send`.** The Azure App Registration must have `Mail.Read` or `Mail.ReadWrite` application permission with tenant-wide admin consent, separate from `Mail.Send`. If the token is acquired but inbox fetch returns 403, this permission is missing. GCC High tenants require consent in the Government portal, not the commercial portal.

16. **Sub-nav active state uses `or`-chained `url_name` checks, not `in` operator.** Django template `in` does substring matching on strings. Always use `{% if request.resolver_match.url_name == 'x' or request.resolver_match.url_name == 'y' %}` for multi-value active detection in the sub-nav bar.

17. **Inbox claim stubs are created on first message open.** When a rep clicks an unlinked message that has no `InboxMessage` DB record yet, a stub record is created with blank `body_html` to enable claim tracking. The full body is only stored at link time (`rfq_inbox_link` view). Do not assume `InboxMessage.body_html` is populated just because the record exists — check `rfq_links` to determine if the message has been fully processed.

18. **`DibbsAward` + `bulk_create` and `auto_now_add`.** Django does not invoke `save()` (or `auto_now_add`) on `bulk_create`. A NOT NULL datetime column on SQL Server plus NULL inserts produces errors (e.g. 8115). AW import timing must continue to use `aw_file_date` and `AwardImportBatch.imported_at`, not a hidden sync timestamp on the award row.

19. **`sol_mass_pass` without `MassPassLog` snapshot.** Removing or reordering the pre-`update()` snapshot + `MassPassLog.objects.create` block breaks **Mass Pass History** and **Undo** (`mass_pass_undo` depends on `snapshot` JSON). Do not delete that block when refactoring bulk pass.

---

## 14. Safe Change Workflow

1. **Read `sales/CONTEXT.md`** for domain background.
2. **Read the specific model/service/view files** directly involved — do not rely on CONTEXT.md alone for field names.
3. **Search for cross-file dependencies** before any rename:
   - Field renames: search `sales/services/`, `sales/views/`, `sales/templates/` for the field name.
   - URL name changes: `grep -r "sales:<name>" sales/templates/` and `sales/base.html`.
   - Status string changes: `grep -r "'<STATUS>'" sales/` (views, services, templates all use raw strings).
4. **Check cross-app impact**: `suppliers.Supplier` field references in `sales/services/email.py`, `matching.py`, `views/suppliers.py`; `contracts.Clin` in `matching.backfill_nsn_from_contracts`.
5. **Make minimal, scoped changes.** Do not refactor adjacent code unless it is directly broken.
6. **Update all coupled files** (see Section 5 clusters).
7. **Run `makemigrations sales`** if any model was changed and review the output.
8. **Verify manually** using the flows in Section 12 relevant to your change.
9. **Do not push** without confirming the BQ export still produces valid 121-column output if any model or export code was touched.

---

## 15. Quick Reference

### Primary files to inspect first
- `sales/models/` (all files — schema is the source of truth)
- `sales/services/bq_export.py` — governs the critical BQ export path
- `sales/services/matching.py` — governs supplier match quality
- `sales/services/email.py` — governs RFQ dispatch
- `sales/services/importer.py` — governs import pipeline
- `sales/views/rfq.py` — largest and most complex view module
- `sales/views/bids.py` — bid builder + export orchestration
- `sales/views/solicitations.py` — list/detail; shared queryset helpers for list + `list_qs` prev/next
- `sales/urls.py` — URL names used throughout templates

### Main coupled areas
- `GovernmentBid` fields ↔ `bq_export.COMPANY_FILLED_COLUMNS`
- `SolicitationLine.bq_raw_columns` ↔ BQ export overlay logic
- `ImportJob.step_results` keys ↔ `import/progress.html`
- `CompanyCAGE.is_default` ↔ every RFQ and BQ export
- `rfq/partials/mailto_buttons.html` ↔ solicitation detail + RFQ pending

### Main cross-app dependencies
- `suppliers.Supplier` — central supplier record; all matching, RFQ, quote, and bid FKs point here
- `contracts.models.Clin` — read by `backfill_nsn_from_contracts()`
- `sales.context_processors.rfq_counts` registered in `STATZWeb/settings.py`

### Main security-sensitive areas
- All views — must retain `@login_required`
- `backfill_nsn` — must retain staff-only guard
- SAM debug JSON — must remain staff-only in `entity_lookup.html`
- `import_batch_delete` — must retain `status='New'` filter

### Riskiest edit types
1. Renaming fields on `GovernmentBid` or `CompanyCAGE` (silent BQ export corruption)
2. Changing `Solicitation.STATUS_CHOICES` values (hardcoded string references everywhere)
3. Touching `sales/services/matching.py` tier logic (affects all downstream bid quality)
4. Removing or restructuring the `CompanyCAGE.is_default` constraint (breaks all RFQ and export flows)
5. Renaming URL patterns in `sales/urls.py` (breaks template `{% url %}` tags silently)
