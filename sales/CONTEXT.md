# Sales Context

## 1. Purpose
The `sales` app owns the DIBBS bidding workflow: it ingests the daily IN/BQ/AS export from DIBBS, triages solicitations, surfaces supplier matches, issues RFQs via `mailto:` flows, captures quotes, builds GovernmentBids, exports the BQ submission file, and tracks awards from DIBBS AW file import (`DibbsAward`). It also exposes supplier capability tooling (NSN/FSC lists, backfill from contracts) plus settings for Company CAGE metadata and email templates. Everything is driven by Django views/templates with no background workers; long-running work happens synchronously via the AJAX/stepper import UI.

## 2. App Identity
- **Django app name:** `sales`
- **AppConfig:** `SalesConfig` (`sales/apps.py`) with label `sales` and verbose name “Sales (DIBBS Bidding)”
- **Filesystem path:** `/sales`
- **Role:** Feature app implementing the DIBBS import → matching → RFQ → bid export lifecycle; tightly coupled to procurement operations rather than generic admin/support utilities.

## 3. High-Level Responsibilities
- Parse and persist DIBBS IN/BQ/AS rows (`sales/services/parser.py`, `sales/services/importer.py`) into `Solicitation`, `SolicitationLine`, `ApprovedSource`, and `ImportBatch`.
- Rank suppliers per line through the three-tier `SupplierMatch` engine plus contract-history backfill (`sales/services/matching.py`).
- Coordinate RFQ dispatch, follow-ups, and `SupplierContactLog` tracking via mailto flows, RFQ Center, and quotes (`sales/views/rfq.py`, `sales/services/email.py`).
- Drive quote-to-bid workflows: select quotes, build `GovernmentBid` drafts, validate/export the BQ submission (`sales/views/bids.py`, `sales/services/bq_export.py`).
- Surface supplier capability tooling for NSN/FSC counts and manual edits, plus searching suppliers with quotes (`sales/views/suppliers.py`).
- Manage settings for `CompanyCAGE`, markup rates, SMTP reply-to values, and `EmailTemplate` defaults consumed by RFQ mailouts (`sales/views/settings.py`, `sales/models/email_templates.py`).
- Integrate with SAM.gov for entity lookup (`sales/services/sam_entity.py`) for the Approved Sources / CAGE tooling (not awards).

## 4. Key Files and What They Do
| File / Directory | Responsibility |
|---|---|
| `models/` package | Defines domain tables: `ImportBatch`, `ImportJob`, the `Solicitation` stack (including `pdf_blob`, `pdf_fetched_at`), supplier capability models (`SupplierNSN`, `SupplierFSC`, `ApprovedSource`), RFQ/quote/bid records (`SupplierRFQ` with `QUEUED` status), `RFQGreeting`, `RFQSalutation`, `NoQuoteCAGE`, `CompanyCAGE`, `EmailTemplate`, `DibbsAward`, `DibbsAwardMod`, unmanaged `WeWonAward` (SQL view-backed wins selector), Graph inbox persistence (`InboxMessage`, `InboxMessageRFQLink`), and match/contact-log data. Many tables reuse `suppliers.Supplier`. |
| `services/parser.py` | Parses fixed-width IN records, 121-column BQ rows, and AS CSVs into helper dataclasses without writing to the database; also assigns initial triage buckets. |
| `services/importer.py` | Coordinates parsing, upserts, and matching for a batch, chunking bulk updates to avoid SQL Server limits, clearing stale approved sources. Runs `_run_lifecycle_sweep()` (New→Active, expired→Archived) at import start. Also contains the legacy `run_import()` entry point. |
| `services/matching.py` | Executes tiered matching (NSN, approved source, FSC), deduplicates by supplier, bulk-creates `SupplierMatch`, and exposes `backfill_nsn_from_contracts()` that reads `contracts.models.Clin`. |
| `services/email.py` | Builds RFQ/follow-up subjects/bodies using the default `CompanyCAGE` and `EmailTemplate`, resolves supplier emails (including `resolve_supplier_email_for_send` for queue: rfq_email → business → primary → contact), and `build_grouped_rfq_email()` for one-per-supplier grouped RFQ emails with `{sol_blocks}`, `{greeting}`, `{salutation}`. Queue dispatch uses Graph or mailto via `build_grouped_rfq_email()`; logs contact history and status updates. |
| `services/graph_mail.py` | Microsoft Graph API mail transport. Provides `send_mail_via_graph(to_address, subject, body, reply_to, attachments)` using MSAL client credentials flow. Called by `build_grouped_rfq_email()` when `GRAPH_MAIL_ENABLED=True`. When `False`, the queue send flow returns `mailto:` URLs for manual dispatch. Env vars: `GRAPH_MAIL_TENANT_ID`, `GRAPH_MAIL_CLIENT_ID`, `GRAPH_MAIL_CLIENT_SECRET`, `GRAPH_MAIL_SENDER`, `GRAPH_MAIL_ENABLED`. `GRAPH_MAIL_SENDER` must be `quotes@statzcorp.com` in production (inherited from Sales Patriot — suppliers recognize this address) and `rfq@statzcorp.com` in local dev/test. Never use a newly provisioned M365 account as sender — new accounts have no sending reputation and are flagged as spam immediately when sending cold RFQs. |
| `services/graph_inbox.py` | Microsoft Graph inbox reader for the `GRAPH_MAIL_SENDER` mailbox. Provides `fetch_inbox_messages()` (returns 50 most recent), `fetch_message_body(graph_message_id)` (on-demand body fetch), and `mark_message_read(graph_message_id)`. Uses GCC High endpoints and the same MSAL client credentials pattern as `graph_mail.py`. Requires `Mail.Read` or `Mail.ReadWrite` application permission. |
| `services/bq_export.py` | Validates `GovernmentBid`s, overlays company/bid data onto `SolicitationLine.bq_raw_columns`, and emits the downloadable 121-column BQ file (raises `BQExportError` with `.errors`). |
| `services/dibbs_fetch.py` | Scrapes DLA’s RFQDates page with `requests`/`BeautifulSoup`, automates Playwright consent/download flows, and extracts IN/BQ/AS files into a temp directory for import. |
| `services/dibbs_pdf.py` | Fetches DIBBS solicitation PDFs via Playwright (same DoD consent bypass as `dibbs_fetch.py`); `fetch_pdf_for_sol(sol_number)` and `fetch_pdfs_for_sols(sol_numbers)` are used by the RFQ queue “Fetch PDFs for Selected” action and by the `fetch_pending_pdfs` management command. `parse_procurement_history(pdf_bytes, sol_number)` — extracts NSN procurement history rows from a raw DIBBS PDF blob using `pypdf`; previously attempted ZIP extraction (incorrect — DIBBS serves raw PDFs). `save_procurement_history(rows)` upserts them into `dibbs_nsn_procurement_history` keyed on `(nsn, contract_number)`. Called inline from `fetch_pdf_for_sol()` after blob is written. |
| `services/sam_entity.py` | SAM.gov Entity Management v3 (CAGE lookup), respecting `SAM_API_KEY` and returning structured set-aside, NAICS, and debug data. (`sam_awards_sync.py` was removed; awards data is AW-file–only.) |
| `services/awards_file_parser.py` | Parses AW file bytes into `AwardFileParseResult` dataclass; validates filename format; no DB writes. |
| `services/awards_file_importer.py` | Routes AW rows by `last_mod_posting_date`: originals (`NULL`) create/upgrade `DibbsAward`; MOD rows (`NOT NULL`) create `DibbsAwardMod` rows. If a MOD arrives first, a synthesized faux `DibbsAward` (`is_faux=True`) is created and linked. `DibbsAward` inserts use raw `executemany` (not `bulk_create`) and MOD rows dedupe on `(award_id, mod_date, nsn, mod_contract_price)`. |
| `views/awards.py` | Staff-only AW file upload view, import result view (session key `aw_import_result`), filterable awards list. |
| `services/no_quote.py` | `normalize_cage_code()` and `get_no_quote_cage_set()` — active `NoQuoteCAGE` codes for solicitation detail / RFQ batch filtering. |
| `views/` package | Hosts the dashboard (`dashboard.py`), import wizard (`imports.py`), solicitation list/detail and search (`solicitations.py` — list uses `_build_list_queryset()` / `_list_qs_before_tab()` / `_apply_list_tab_filter()` / `_apply_list_sort()` so filters match detail prev/next nav), RFQ center/actions (`rfq.py`, including `supplier_create_and_queue` for SAM modal save + queue; `rfq_manual_supplier_search` (JSON search endpoint) and `rfq_queue_add_manual` (POST staging endpoint) for manually adding any in-system supplier to the RFQ queue from the Solicitation Detail Matches tab), bid center (`bids.py`), supplier tooling (`suppliers.py`), settings (`settings.py`), SAM entity lookup (`entity_lookup.py` — HTML page plus `?fmt=json` for modal prefill), and `context_processors.py`. |
| `templates/sales/` | Contains every screen: dashboard, import upload/progress/history, solicitation list/detail, RFQ pending/center/sent/quote entry/partials, bid builder/export/history, supplier list/detail/backfill, settings (cages, email templates, RFQ greetings, RFQ salutations), and entity lookup pages. |
| `urls.py` | Defines the `sales:` namespace for dashboard, import steps, solicitations, RFQ endpoints, bids, suppliers, settings, awards list/import, and entity lookup. |
| `forms.py` | Declares `ImportUploadForm` (three file fields) used by upload/fetch views, `AwardUploadForm` for AW file import; `QuoteEntryForm` lives inside `views/rfq.py` and enforces numeric/text validation for quotes. |
| `context_processors.py` | Adds `overdue_rfq_count` globally by counting SENT RFQs whose solicitation return date is in the past. |
| `migrations/` | Tracks schema evolution from 0001 through 0025+ (includes `NoQuoteCAGE` / `dibbs_no_quote_cage`, buckets, RFQ extras, bids, import jobs, awards + AW import batch, email templates, manual match method, historical CAGE/IMAP migrations superseded by Graph inbox in `0020_graph_inbox_and_remove_imap`, solicitation PDF fields, RFQ greeting/salutation tables, inbox claim timestamps, solicitation status lifecycle, `DibbsAward.aw_file_date`, removal of legacy `DibbsAward` SAM-era fields, removal of `DibbsAward.synced_at`). The `suppliers` app has a separate migration for `Supplier.rfq_email`. |

## 5. Data Model / Domain Objects
- **Import models:** `ImportBatch` records each DIBBS run, `ImportJob` tracks the AJAX multi-step upload (temp file paths, status, `step_results`).
- **Solicitation stack:** `Solicitation` holds numbers, status, buckets, return dates, optional `pdf_blob` (BinaryField) and `pdf_fetched_at` (DateTimeField) for stored DIBBS PDFs, `pdf_fetch_status` (CharField, nullable) — `PENDING` / `FETCHING` / `DONE` / `FAILED`. Set to `PENDING` when a sol is added to the RFQ queue and `pdf_blob` is null; managed by `fetch_pending_pdfs`. `pdf_fetch_attempts` (PositiveSmallIntegerField, default 0) — incremented on each failed fetch; sols with five or more attempts are permanently skipped by that command. Links to `SolicitationLine`. `SolicitationLine` has NSN text, quantities, delivery days, and `bq_raw_columns` JSON (copy of the BQ row) for later export. Each line connects to matches, quotes, and bids. `NsnProcurementHistory` (`dibbs_nsn_procurement_history`) — NSN-keyed ledger of historical DLA purchases extracted from DIBBS solicitation PDF text. Unique on `(nsn, contract_number)`. NSN stored normalized (no hyphens).

### Solicitation Status Lifecycle

**Status values and their meanings:**
- `New` — Imported in today's import batch only. Transitioned to `Active` on the next import run.
- `Active` — Carried over from a prior import. Still within return-by date. Untouched by sales team.
- `Archived` — Past return-by date AND in a terminal/untouched state. Hidden from default views.
- Pipeline statuses (`RFQ_PENDING`, `RFQ_SENT`, `QUOTING`, `BID_READY`, `BID_SUBMITTED`) — never auto-archived.

**Lifecycle transitions:**
- `New → Active`: Triggered at the start of each import run via `_run_lifecycle_sweep()` in `importer.py`.
  Any `New` record whose import batch date is before today is flipped to `Active`.
- `Active/New/NO_BID + SKIP bucket → Archived`: Also triggered in `_run_lifecycle_sweep()`.
  Any record past `return_by_date` that is not in an active pipeline status is archived.

**Archive view:** `/sales/solicitations/archive/` — read-only BD mining view.
Supports filtering by set-aside, item type, date range, NSN/nomenclature. Paginated at 50/page.

**TODO (deferred — confirm with sales team):**
What happens to mid-pipeline solicitations (RFQ_SENT, QUOTING, BID_READY) when their
return_by_date passes? Currently they are excluded from archiving and remain in their
pipeline status indefinitely. Sales team input needed on correct behavior.
- **Matching/capability models:** `SupplierMatch` stores the winning tier, `ApprovedSource` keeps AS data, `SupplierNSN`/`SupplierFSC` store internal capability records, and manual entries are flagged with source marks. Manual supplier additions from solicitation detail create a `SupplierMatch` with `match_method='MANUAL'` and `match_tier=3`. No new model fields are required; `manual_rfqs` is surfaced on the Solicitation Detail context via a filtered queryset.
- **RFQs and quotes:** `SupplierRFQ` links a line to `suppliers.Supplier`, records sent/follow-up timestamps/status choices (including `QUEUED` as the first status), and references `settings.AUTH_USER_MODEL` for `sent_by`. `SupplierQuote` keeps the supplier’s pricing/lead time/note, while `SupplierContactLog` tracks every touchpoint (method, direction, summary).
- **RFQ phrases:** `RFQGreeting` and `RFQSalutation` (tables `dibbs_rfq_greeting`, `dibbs_rfq_salutation`) store optional opening/closing phrases for outbound RFQ emails; managed via Settings (Greetings / Salutations).
- **Bids and company data:** `GovernmentBid` stores DIBBS submission data (cage codes, pricing, manufacturer, part number info, margin). `CompanyCAGE` holds markup, compliance codes, SMTP reply-to, and default/active flags. `EmailTemplate` stores content with `_SafeDict` rendering; one template is marked `is_default`.
- **Inbox models:** `InboxMessage` stores emails from the `GRAPH_MAIL_SENDER` mailbox that a sales rep has linked to one or more RFQs. `InboxMessage` also carries three claim fields: `claimed_by` (FK to User), `claimed_at`, and `claim_expires_at`. Claims expire after 20 minutes. When a rep opens a message detail, a claim is written (or refreshed) in the same AJAX request that fetches the body. A second rep opening the same unlinked message within 20 minutes sees a warning banner and has linking disabled. An override option allows the second rep to take the claim after a confirmation step. Claim logic does not apply to already-linked messages. `InboxMessageRFQLink` is the many-to-many bridge between `InboxMessage` and `SupplierRFQ` — one supplier reply covering multiple grouped SOLs can be linked to each of its RFQs independently.
- **Awards:** `DibbsAward` is populated from AW originals and can be marked `is_faux=True` when synthesized as a placeholder for MOD-first imports. `DibbsAwardMod` stores modifications separately in `dibbs_award_mod` (instead of overwriting `DibbsAward`). MOD detection is `last_mod_posting_date IS NOT NULL`; original-award detection is `last_mod_posting_date IS NULL`. `we_won` is still derived from active `CompanyCAGE` matching and applies to faux rows too. `AwardImportBatch` now tracks: `awards_created`, `faux_created`, `faux_upgraded`, `mods_created`, `mods_skipped`, `row_count`, `we_won_count`.
- **No Quote list:** `NoQuoteCAGE` (table `dibbs_no_quote_cage`) tracks CAGE codes that have declined to work with us. Soft-delete via `is_active` + `deactivated_at`. Entries are added from the sales supplier profile (`/sales/suppliers/<id>/`), SAM entity lookup (`/sales/entity/cage/<cage>/`), and managed (restore) on the staff Settings page `/sales/settings/no-quote/`.
- **Cross-app references:** Supplier relations point to `suppliers.Supplier` (table `contracts_supplier`); `Supplier` has an optional `rfq_email` field settable via the supplier profile RFQ Email picker in the suppliers app. Matching backfill queries `contracts.models.Clin`.

## 6. Request / User Flow
1. **Daily import:** `/sales/import/` (`import_upload`) on GET shows **Fetch from DIBBS** (POST `import_fetch_dibbs`, optional `fetch_date`) and a **manual upload** path: client-side file pick → confirm → POST `import_upload` with IN/BQ/AS. There is no SAM.gov awards option, `skip_sam` field, or related query flag on redirect to progress. Uploaded or fetched files land in a temp directory, an `ImportJob` is created, and the user is redirected to `/import/job/<job_id>/`, which runs four AJAX POSTs (`parse`, `solicitations`, `lines`, `match`). The **parse** step runs `_run_lifecycle_sweep()` first (New→Active, expired→Archived) before `create_import_batch`. Each step reuses the parsing/upsert/matching services. `import_fetch_dibbs` prefetches files via Playwright; `import_batch_delete` cleans up only `Solicitation.status='New'` and related lines/sources. `import_history` lists previous batches.
2. **Awards import (separate flow):** Staff download the daily AW file from `files.themanihome.com`, then upload it at `/sales/awards/import/`. `awards_file_parser.parse_aw_file()` validates the filename and parses rows. `awards_file_importer.import_aw_file()` routes rows to `DibbsAward` (original awards) or `DibbsAwardMod` (MODs), synthesizing faux awards as needed for MOD-first arrivals. Return payload includes: `created_count`, `faux_created_count`, `updated_faux_count`, `mod_created_count`, `mod_skipped_count`, `we_won_count`, `we_won_by_cage`, and `warnings`. An `AwardImportBatch` record is created with matching batch-level counters. Wins reporting lives at `/sales/awards/wins/` and is driven dynamically by `WeWonAward` while excluding faux awards from win aggregates.
3. **Solicitation browsing:** `/sales/solicitations/` lists **exclude `Archived`** by default (shared `_list_qs_before_tab()` / `_build_list_queryset()` contract for list + detail prev/next). **Archive** (`/sales/solicitations/archive/`) is a read-only filtered list of `status='Archived'`. The page offers four filter tabs: **Matches**, **Set-Asides**, **Unrestricted**, and **No-Bid** (`?tab=nobid`). The first three exclude `status='NO_BID'`; **No-Bid** shows only `NO_BID`. Tab rules: Matches = at least one `SupplierMatch`; Set-Asides = `small_business_set_aside` not unrestricted (including null as unrestricted); Unrestricted = unrestricted set-aside codes. The filter bar (set-aside, status, line item type, full-text search on sol # and nomenclature), optional `?sort=` column sort, and bulk bucket reassignment apply as before. The same record may satisfy more than one tab’s rules, but only one tab is active per request. List rows link to detail with `?list_qs=<urlencoded snapshot>` (all current GET params except `page`) so the detail page can show **Back to list**, **Prev**, and **Next** in list order without session state. Detail view (`solicitations/<sol_number>/`) shows a nav bar when `list_qs` is present, the pipeline ribbon, **status banners** for non–New/Matching statuses (e.g. `RFQ_PENDING` uses `queued_rfq_count` from `SupplierRFQ` rows with `QUEUED` on this solicitation’s lines), **Matches** tab with queue-only actions (matched suppliers and in-system approved sources use **+ Add to Queue** / `rfq_queue_add`; not-in-system approved sources use **+ Add & Queue**, which opens a SAM.gov modal), RFQ/quote/bid tabs, approved sources, contact log, and embedded bid builder context. Context includes `queued_supplier_ids`, `prev_sol`, `next_sol`, `list_qs`, and `queued_rfq_count` where applicable. Status transitions: adding to queue advances `New`/`Active`/`Matching` → `RFQ_PENDING`; sending from queue advances `RFQ_PENDING` → `RFQ_SENT`. `/sales/search/` supplies top-bar typeahead and JSON results (search hits do not automatically pass `list_qs`). A third section, **Manually Added**, appears below Matched Suppliers. The **+ Add Supplier** button opens a Bootstrap modal with a live-search field (min 2 chars, 300ms debounce) that queries `rfq_manual_supplier_search`. Selecting a result POSTs to `rfq_queue_add_manual`, which enforces No Quote and duplicate checks before creating the `SupplierRFQ(status=QUEUED)` and `SupplierMatch(match_method=MANUAL)`.
4. **RFQ orchestration:** `/sales/rfq/` (pending queue) lists unmatched matches; buttons call `rfq_mailto` to build a `mailto:` URL from the default `EmailTemplate`, and `rfq_mark_sent` records SENT status. Batch or single send actions create `SupplierRFQ` records, attempt to email, and report success/failure. RFQ navigation is now handled by the shared secondary sub-nav in `sales/base.html` (`section='rfq'`) with Queue (`/sales/rfq/queue/`), Manage (`/sales/rfq/center/`), and Inbox (`/sales/rfq/inbox/`). The queue page lists all `QUEUED` RFQs grouped by supplier; users can “Fetch PDFs for Selected”, “Send Selected”, or “Send All”. One grouped email per supplier is built via `build_grouped_rfq_email()`: with `GRAPH_MAIL_ENABLED=True` mail is sent via Microsoft Graph and RFQs move to SENT immediately; with `False`, the page shows **Open in Email** links plus **Mark All Sent** (`rfq_queue_mark_sent`) after manual send. **Inbox** (`/sales/rfq/inbox/`) is a separate page that reads supplier replies from the shared mailbox via Microsoft Graph (`graph_inbox.py`); reps link messages to `SupplierRFQ` rows and open quote entry from linked RFQs. `/sales/rfq/center/` renders an AJAX-driven three-panel UI for sent RFQs, with `/rfq/center/<id>/detail/` returning fragments. Secondary actions include entering quotes (`rfq_enter_quote`), follow-ups, marking no-response/declined, selecting quotes for bids, and sending RFQs to approved-source/adhoc/existing suppliers plus supplier search.
5. **Quote → bid → export:** `SupplierQuote` entries feed the Bid Center (`/sales/bids/`). `bid_builder` preloads selected or cheapest quotes, validates unit price/delivery/cages, and saves `GovernmentBid`. The `bid_builder` view also queries `DibbsAward` for the line's NSN (stripping hyphens for matching) and passes `last_award` (most recent award with a price), `award_history` (up to 5 most recent), and `last_award_price_raw` (string for JS) to the template. The Price Anchor card shows Last Award Price as a middle column. An orange "Bid Above Last Award" badge appears on page load if `suggested_bid_price > last_award.total_contract_price`. A "See History" link opens a modal with the 5 most recent awards for the NSN. Draft bids can be marked ready, shown on `bids/export/`, and exported via `bids/export/download/`, which calls `generate_bq_file`. Exported bids update `bid_status`/`submitted_at`, stamp the BQ filename, and flip the solicitation to `BID_SUBMITTED`. `bids/history/` surfaces submitted bids and allows marking solicitations `WON`, `LOST`, or `NO_BID`.
6. **Suppliers & capabilities:** `/suppliers/` lists active suppliers with NSN/FSC/quote counts, optionally filtered by name or cage. Detail pages provide tabs for profile/capabilities/quote history. Add/remove NSN and FSC forms validate inputs (13-digit NSNs, four-character FSCs) and save manual records. Sales supplier profile (`/sales/suppliers/<id>/`) supports **Flag as No Quote** (POST `supplier_no_quote_add`) when a CAGE is present. `backfill_nsn` is a staff-only view that runs `matching.backfill_nsn_from_contracts()`, optionally in dry-run mode.
7. **Settings & SAM:** `/sales/settings/` redirects to the `CompanyCAGE` list; add/edit forms adjust compliance codes, markup, and SMTP reply-to, ensuring only one default cage. The settings landing links to **RFQ Greetings**, **RFQ Salutations**, and **No Quote CAGEs** (`/sales/settings/no-quote/`, staff — list active + restore / history). `/sales/settings/email/` lists templates, `email_template_edit` manages creation/update, and `email_template_preview` renders sample data via `_SafeDict`. `/sales/entity/cage/<cage_code>/` calls `sam_entity.lookup_cage`, handles missing API keys/errors gracefully, and renders SAM metadata (staff sees raw JSON); `?fmt=json` returns the same lookup as structured JSON for client-side prefill (e.g. solicitation detail SAM modal). The same path supports POST to `entity_no_quote_add` from the **Flag as No Quote** modal. The suppliers app supplier profile page includes an RFQ Email widget (picker for business/primary/contact emails or manual entry) that POSTs to `suppliers:supplier_set_rfq_email` to set `Supplier.rfq_email`.

## 7. Templates and UI Surface Area
- `sales/base.html` supplies a primary navigation bar (Dashboard, Solicitations, Archive, RFQ Center, Bid Center, Suppliers, Import, Awards, Settings) and a context-driven secondary sub-nav bar that appears beneath the primary bar when the user is inside a section with sub-pages. RFQ Center sub-nav: Queue | Manage | Inbox. Bid Center sub-nav: Active | Bid History. Settings sub-nav: CAGEs | No Quote CAGEs | Email Templates | Greetings | Salutations. The `section` context variable (set per view) controls which secondary bar renders. Top-bar search targets `sales:global_search`.
- Import templates: `sales/import/upload.html` (DIBBS fetch form + two-step manual upload UI; no SAM sync controls), `sales/import/progress.html` (four-step AJAX checklist), and `sales/import/history.html`. Awards: `sales/awards/import_upload.html`, `sales/awards/import_result.html`, `sales/awards/list.html`.
- Solicitations use `sales/solicitations/list.html` (four tabs — Matches / Set-Asides / Unrestricted / No-Bid; pipeline tabs exclude `NO_BID`; filter bar; column sort; bulk reassignment; row links append `list_qs` from `filter_snapshot`), `sales/solicitations/archive.html` (read-only archived list with filters), and `sales/solicitations/detail.html` (optional prev/next + back-to-list nav when `list_qs` is set; pipeline ribbon; status banners for active pipeline statuses; **Matches** tab: matched suppliers and approved sources wired to the RFQ queue; SAM modal for create-supplier-and-queue; RFQ/quote/bid tabs; contact log; bid builder context).
- RFQ screens include `sales/rfq/pending.html`, `sales/rfq/center.html`, `sales/rfq/inbox.html` (Graph mailbox inbox + link-to-RFQ UI), `sales/rfq/queue.html` (full-width queue by supplier), plus `sales/rfq/partials/center_panel.html` and `sales/rfq/partials/mailto_buttons.html`, `sales/rfq/sent.html`, and `sales/rfq/quote_entry.html`.
- Bid screens: `sales/bids/ready.html`, `sales/bids/builder.html`, `sales/bids/export_queue.html`, and `sales/bids/history.html`.
- Supplier screens: `sales/suppliers/list.html`, `sales/suppliers/detail.html`, `sales/suppliers/add_nsn.html`, `sales/suppliers/add_fsc.html`, and `sales/suppliers/backfill_nsn.html`.
- Settings screens: `sales/settings/cages.html`, `sales/settings/cage_form.html`, `sales/settings/email_templates.html`, `sales/settings/email_template_form.html`, `sales/settings/greetings.html`, `sales/settings/salutations.html`, `sales/settings/no_quote_list.html`, with the email preview endpoint providing JSON for live previews.
- SAM lookup page: `sales/entity_lookup.html` renders found/not-found/error states and displays `debug_raw_json` only to staff users. The same view (`entity_cage_lookup`) accepts `?fmt=json` and returns a flat JSON payload (`name`, `website`, `physical_address` line1–zip, `mailing_address`, `error`) mapped from `lookup_cage()` for the solicitation detail SAM modal.

## 8. Admin / Staff Functionality
- There are no model registrations in `sales/admin.py`; all staff actions go through the custom views.
- Staff-only endpoints (`backfill_nsn`, `awards_import_upload`) check `request.user.is_staff` or use `@user_passes_test`.
- Settings and import history screens assume staff access; the Django admin is unused.

## 9. Forms, Validation, and Input Handling
- `ImportUploadForm` requires the IN, BQ, and AS files and is shared between upload and fetch flows.
- `QuoteEntryForm` (defined inside `views/rfq.py`) coerces decimals/integers, enforces non-negative prices and lead times, trims text fields, and exposes an `errors` dict for AJAX callers.
- `supplier_add_nsn` and `supplier_add_fsc` normalize inputs (strip hyphens, enforce length) and rely on Django messages to communicate validation errors.
- `bid_builder` sanitizes cage codes, bid types, and money/delivery inputs, enforces positive unit price/delivery, and recalculates margins before saving `GovernmentBid`.
- Settings forms call helpers to build choice tuples for SB representations, affirmative action, and previous contracts while the email preview uses `_SafeDict` to avoid `KeyError`.

## 10. Business Logic and Services
- `sales/services/importer.py` orchestrates parsing, batch creation, line upserts, approved source refreshes, and matching, chunking bulk operations to stay within SQL Server parameter limits. Each import begins with `_run_lifecycle_sweep()` (before a new batch is created in the AJAX parse step). `run_import()` wraps the full pipeline and runs the same sweep first.
- `sales/services/parser.py` contains `parse_in_file`, `parse_bq_file`, `parse_as_file`, and helpers for NSN formatting, date parsing, and bucket assignment.
- `sales/services/matching.py` batches tier 1–3 lookups, skips part-number items for direct NSN matches, deduplicates suppliers by lowest tier, bulk-creates `SupplierMatch`, and offers `backfill_nsn_from_contracts()` that weights `contracts.Clin` recency.
- `sales/services/email.py` renders RFQ/follow-up bodies with approved source info, set-aside data, and `dibbs_pdf_url`, resolves supplier emails (contact → primary → business; for queue send: `resolve_supplier_email_for_send` uses rfq_email → business_email → primary_email → first contact). `build_grouped_rfq_email(supplier, rfqs, sent_by)` builds one email per supplier for the queue with `{sol_blocks}`, `{greeting}`, `{salutation}` from the default `EmailTemplate`. **RFQ queue send:** when `GRAPH_MAIL_ENABLED=True`, sends via `graph_mail.send_mail_via_graph` (GCC High: `graph.microsoft.us`); when `False`, returns a `mailto:` URL and the user confirms with `rfq_queue_mark_sent`. Non-queue paths (pending batch/single send, follow-up) still use Django `EmailMessage` / SMTP with `Reply-To` from `CompanyCAGE.smtp_reply_to` (fallback `DEFAULT_FROM_EMAIL`); `from_email` is `DEFAULT_FROM_EMAIL`, aligned with `EMAIL_HOST_USER` for Microsoft 365. SMTP credentials come from env (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`); M365 uses port 587 STARTTLS (`EMAIL_USE_TLS=True`, `EMAIL_USE_SSL=False`). Graph Mail env vars (`GRAPH_MAIL_*`) are separate from SMTP (`EMAIL_*`) and from Azure AD auth (`MICROSOFT_AUTH_*`). Do not conflate these three credential sets. Queue sends attach PDFs (Graph or mailto body); `SupplierContactLog` entries are created on successful Graph send or after mailto confirmation.
- `sales/services/bq_export.py` overlays company/bid fields onto the stored 121-column templates, formats prices/delivery fields, enforces column lengths, and raises `BQExportError` when validation fails.
- `sales/services/dibbs_fetch.py` performs DIBBS discovery with `requests`/`BeautifulSoup` and drives Playwright automation to download IN/BQ/AS files for import.
- `sales/services/dibbs_pdf.py` fetches DIBBS solicitation PDFs via Playwright (same DoD consent bypass as `dibbs_fetch.py`); `fetch_pdf_for_sol(sol_number)` returns raw PDF bytes or `None` and runs procurement-history extraction on success; `fetch_pdfs_for_sols(sol_numbers)` returns a dict `sol_number -> bytes | None`. The RFQ queue “Fetch PDFs” action and the `fetch_pending_pdfs` command persist blobs then call `parse_procurement_history` / `save_procurement_history` after each successful fetch.
- `sales/services/sam_entity.py` hits SAM’s Entity API, maps SBA codes to set-aside flags, collects NAICS/PSC data, and returns structured payloads (including `debug_raw_json` for staff).
- `sales/services/suppliers.py` helper functions materialize suppliers from SAM results or stub values when cage codes are not yet in the supplier database, with notes tagged `[SAM]` or `[STUB]`.

## 11. Integrations and Cross-App Dependencies
- Relies on `suppliers.Supplier` (`contracts_supplier`) for matches, RFQs, quotes, and supplier search forms; multiple services/views import `Supplier`. `Supplier.rfq_email` is the preferred RFQ dispatch address and is settable via the supplier profile picker in the suppliers app.
- `matching.backfill_nsn_from_contracts()` reads `contracts.models.Clin` to seed `SupplierNSN`.
- `SupplierRFQ.sent_by` and contact logs reference `settings.AUTH_USER_MODEL`.
- External HTTP dependencies: SAM.gov Entity API via `requests` (entity lookup) and DIBBS downloads via `requests`, `BeautifulSoup`, and Playwright. Missing `SAM_API_KEY` triggers graceful degradation for entity lookup.
- Settings references include `DEFAULT_FROM_EMAIL` for RFQ emails and the `sales.context_processors.rfq_counts` entry in `STATZWeb/settings.py`.
- **RFQ sender mailbox decision (standing):** Production sends use `quotes@statzcorp.com` (set via `GRAPH_MAIL_SENDER` in Azure App Service config) — this is the same address used by the legacy Sales Patriot platform and has established supplier recognition and sending reputation. Dev/test sends use `rfq@statzcorp.com` (set in local `.env`). Do not change the production sender without notifying the sales team — suppliers have existing email relationships with `quotes@statzcorp.com`.

## 12. URL Surface / API Surface
Major routes (namespace `sales:`) include:
- `/` → `dashboard`
- `/import/` plus `import/fetch-dibbs/`, history, delete, and the four AJAX steps (`parse`, `solicitations`, `lines`, `match`)
- `/solicitations/` list/detail, `solicitations/<sol_number>/nobid/`, `/search/`
- `/rfq/` pending, center, sent, mailto, mark-sent, send-batch, enter-quote, follow-up, no-response/declined, cage preview, approved-source/adhoc/existing send, supplier search; **inbox (Graph):** `rfq/inbox/`, `rfq/inbox/body/<graph_message_id>/`, `rfq/inbox/link/<graph_message_id>/`, `rfq/inbox/rfq-search/`; **queue:** `rfq/queue/` (view), `rfq/manual-supplier-search/` (GET JSON), `rfq/manual-queue-add/` (POST JSON), `rfq/queue/add/`, `rfq/supplier-create-and-queue/` (`supplier_create_and_queue` — POST creates or reuses `suppliers.Supplier` by CAGE, optional `contracts.Address` for physical address, queues `SupplierRFQ`), `rfq/queue/fetch-pdfs/`, `rfq/queue/send/` (POST full-page: Graph redirect or mailto confirm UI), `rfq/queue/mark-sent/` (POST mailto confirm)
- `/quotes/<id>/select-for-bid/`
- `/bids/` ready list, builder, select quote, export queue, export download, history
- `/suppliers/` list/detail plus NSN/FSC add/remove and `backfill-nsn/`
- `/settings/` cages, cage add/edit, email template list/edit/new/delete/set-default, preview, greetings and salutations (list/add/delete/toggle), **no-quote** list + deactivate (`/sales/settings/no-quote/`)
- `/awards/` (list, filterable), `/awards/import/` (staff upload), `/awards/import/result/` (import summary)
- `/entity/cage/<cage_code>/` (optional `?fmt=json` for structured SAM data without HTML), `/entity/cage/<cage_code>/no-quote/add/` (POST)

AJAX and API responses return JSON (import steps, RFQ center detail, `rfq_mailto`, `rfq_mark_sent`, quote entry when called via fetch).

## 13. Permissions / Security Considerations
- Every view is decorated with `@login_required`; RFQ/import actions rely on `request.user` for logging `sent_by` and `logged_by`.
- Staff-only checks guard `backfill_nsn` and determine whether SAM debug JSON is shown.
- `import_batch_delete` only removes `Solicitation.status='New'` rows so work in progress is preserved.
- RFQ flows avoid SMTP by generating `mailto:` URLs; `rfq_mark_sent` records the action once the human confirms sending.
- IN/BQ/AS uploads contain sensitive procurement data; temporary files live under `/tmp` directories that are removed during the matching step.

## 14. Background Processing / Scheduled Work

Background workers: DIBBS awards scraper and DIBBS solicitation PDF fetcher.

**`fetch_pending_pdfs`** — Queries `Solicitation` for `pdf_fetch_status` in `PENDING` or `FAILED` (retry) with `pdf_fetch_attempts < 5`. Opens one shared Playwright browser session via `fetch_pdfs_for_sols()`, fetches all matching PDFs, saves blobs, runs procurement history parse/save. Marks `DONE` on success, `FAILED` on failure (increments `pdf_fetch_attempts`). After five failures a sol is permanently skipped. Designed to run every five minutes as an Azure WebJob during office hours. All ORM calls happen outside the Playwright session boundary (Azure mssql requirement).

**Entry point:** `python manage.py scrape_awards [--date YYYY-MM-DD] [--dry-run]`
**Scheduler:** Azure WebJob (`webjobs/run_scrape_awards/run.sh`) — nightly schedule
**Service:** `sales/services/dibbs_awards_scraper.py`

### Scraper Architecture

The scraper runs in four clean phases. All Django ORM calls are strictly separated
from Playwright browser sessions — NO ORM inside any `with sync_playwright()` block.

**Phase 1 — Inventory (browser, no ORM)**
  Opens browser → hits AwdDates.aspx → gets full available date list → closes browser.

**Phase 2 — Sync dates to DB (pure ORM)**
  For each date on DIBBS not yet in AwardImportBatch → INSERT with scrape_status='MISSING'.

**Phase 3 — Scrape loop (one browser session per date)**
  Queries non-SUCCESS dates oldest-first. For each date:
    - Opens browser → scrapes all pages → for each page: calls on_page_complete callback
      (which saves records to DB) → waits 2 seconds → closes browser.
    - Updates AwardImportBatch with final status after browser closes.

**Phase 4 — Notification check (pure ORM + Graph mail)**
  Finds non-SUCCESS dates where scrape_date <= today - 38 days.
  Sends email via Graph to AWARDS_ALERT_EMAIL env var + shows warning banner on UI.

### Scrape Status Values
- MISSING — date exists on DIBBS, not yet attempted
- IN_PROGRESS — currently being scraped (or crashed mid-scrape)
- SUCCESS — actual_rows == expected_rows, complete
- PARTIAL — completed but row count mismatch, eligible for retry
- FAILED — exception thrown, eligible for retry

### Danger Zone Logic
DIBBS keeps ~45 days of award data. Any non-SUCCESS date where
`today - scrape_date >= 38 days` is in the danger zone and triggers
email notification + UI warning banner.

### Required Environment Variables
- GRAPH_MAIL_ENABLED, GRAPH_MAIL_TENANT_ID, GRAPH_MAIL_CLIENT_ID,
  GRAPH_MAIL_CLIENT_SECRET, GRAPH_MAIL_SENDER — same as RFQ mail system
- **AWARDS_ALERT_EMAIL** — set in Azure App Service Configuration to the email address that should receive award scraper alert emails (expiry / retention warnings **and** a **job failure** alert whenever `scrape_awards` exits non-zero: invalid `--date`, missing Playwright, or one or more dates ending in `FAILED`; same Graph settings as RFQ mail).

### Per-Page Save Pattern
Records are saved to DB after each page (50 rows), not accumulated in memory.
AwardImportBatch.pages_scraped and row_count are updated after each page.
This means a crashed scrape retains all data from completed pages.

The solicitation import pipeline runs entirely via HTTP (AJAX steps on `ImportJob`). `fetch_dibbs_archive_files` requires Playwright/Chromium for `/import/fetch-dibbs/` (IN/BQ/AS — separate from awards). `backfill_nsn_from_contracts` is a manual staff view (dry run supported).
## 15. Testing Coverage
`tests.py` is the default Django stub with no test cases. There are no unit/integration tests for parser, importer, matching, RFQ flows, or service helpers; adding targeted tests for `sales/services/bq_export.py`, `sales/services/parser.py`, and RFQ workflows would cover high-risk areas.

## 16. Migrations / Schema Notes
- `0001_initial`: core solicitation/line models, import tables, RFQ scaffolding.
- `0002_suppliermatch_match_score_suppliernsn_last_synced_and_more`: adds `SupplierMatch`, `SupplierNSN.match_score`, and last-synced metadata.
- `0003_add_solicitation_bucket`: introduces `bucket`/`bucket_assigned_by` on `Solicitation`.
- `0004_rfq_extra_fields_and_cage_smtp`: adds RFQ fields (follow-up timestamps, `email_sent_to`, `declined_reason`) and `CompanyCAGE.smtp_reply_to`.
- `0005_bq_raw_columns_and_bid_fields`: adds `bq_raw_columns` JSON and expands `GovernmentBid` with manufacturer/part-number fields.
- `0006_add_hubzone_requested_by`: tracks hubzone requests on `Solicitation`.
- `0007_add_importjob`: creates `ImportJob` for the AJAX workflow.
- `0008_add_dibbs_award`: adds the `DibbsAward` table.
- `0009_email_template`: adds `EmailTemplate` with ordering/default behavior.
- `0010_suppliermatch_manual_method`: adds the `MANUAL` choice for ad-hoc matches.
- Later migrations (0011–0015): CompanyCAGE IMAP/OAuth and cleanup.
- `0016_solicitation_pdf_fields`: adds `pdf_blob` and `pdf_fetched_at` to `Solicitation`.
- `0030_solicitation_pdf_fetch_attempts_and_more`: adds `pdf_fetch_status` and `pdf_fetch_attempts` to `Solicitation`.
- `0017_rfqgreeting_rfqsalutation`: creates `RFQGreeting` and `RFQSalutation` (tables `dibbs_rfq_greeting`, `dibbs_rfq_salutation`).
- `0018_no_quote_cage`: adds `NoQuoteCAGE` (`dibbs_no_quote_cage`) with partial unique constraint on active `cage_code`.
- `0019_award_import_batch_and_dibbs_award_file_fields`: adds `AwardImportBatch` table (`dibbs_award_import_batch`) and new DIBBS-file fields on `DibbsAward` (`source`, `award_basic_number`, `delivery_order_number`, `delivery_order_counter`, `last_mod_posting_date`, `total_contract_price`, `posted_date`, `nsn`, `nomenclature`, `purchase_request`, `dibbs_solicitation_number`, `aw_import_batch` FK).
- `0020_graph_inbox_and_remove_imap`: creates `InboxMessage` / `InboxMessageRFQLink` (`dibbs_inbox_message`, `dibbs_inbox_message_rfq_link`), removes remaining `CompanyCAGE` IMAP fields, deletes legacy `InboxEmail` / `sales_inbox_email`.
- `0021_inboxmessage_claim_expires_at_and_more`: adds `InboxMessage.claimed_by`, `claimed_at`, and `claim_expires_at`.
- `0022_solicitation_status_lifecycle`: expands `Solicitation.status` choices to the full pipeline (`Active`, `Matching`, `WON`, `LOST`, `Archived`, etc.).
- `0023_dibbsaward_aw_file_date`: adds `DibbsAward.aw_file_date` with data migration backfill for existing `DIBBS_FILE` rows.
- `0024_remove_dibbsaward_award_amount_and_more`: removes legacy SAM-era fields from `DibbsAward` (`award_amount`, `awardee_name`, `sam_data`, `we_bid`).
- `0025_remove_dibbsaward_synced_at`: removes `synced_at` from `DibbsAward` (redundant with `AwardImportBatch.imported_at` and `aw_file_date`; `bulk_create` bypasses `save()` so `auto_now_add` never ran, which broke NOT NULL `datetimeoffset` on SQL Server).
- In the `suppliers` app, a Django-generated migration adds `rfq_email` to `Supplier`.
Schema evolution reflects RFQ/bid feature rollouts; no large legacy migrations remain.

## 17. Known Gaps / Ambiguities
- There are no automated tests; `sales/tests.py` still contains the default stub.
- `sales/admin.py` does not register any models, so staff rely entirely on the custom UI rather than the Django admin.
- RFQ mailto flows assume suppliers expose `contact`, `primary_email`, or `business_email`; if none exist the UI prompts for email manually but does not fill it automatically.
- `sales/services/dibbs_fetch.py` requires Playwright + Chromium, but the repo lacks documentation or tooling to install them, so `/import/fetch-dibbs/` fails unless the environment already has Playwright binaries.
- `SupplierMatch` tier logic skips NSN/approved-source matching for `item_type_indicator == '2'`, so part-number-only lines rely solely on FSC or manual matches; this behavior is drawn from the code but not explicitly explained elsewhere.
- IMAP integration has been fully removed. The inbox is powered by Microsoft Graph (`graph_inbox.py`) reading the `GRAPH_MAIL_SENDER` mailbox directly. Requires `Mail.Read` or `Mail.ReadWrite` application permission with tenant-wide admin consent on the Azure App Registration.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- If you change solicitation list filters, tabs (`VALID_TABS` / `?tab=`), default ordering, or column sort behavior, update **`sales/views/solicitations.py`** so `_build_list_queryset()` (and its helpers) stay in lockstep; otherwise **Prev/Next** on the detail page will disagree with the list. `list.html` passes filters via `filter_snapshot` / `list_qs`.
- If `SolicitationLine.bq_raw_columns` is renamed or its JSON shape changes, update `sales/services/bq_export.py` and ensure the importer still populates it; missing templates trigger `BQExportError`.
- Additional matching tiers or match method changes must update `sales/services/matching.py` (deduplication, scoring) and downstream UI filters that expect the existing `match_method` choices.
- Any status transition for RFQs should consider `sales/context_processors.rfq_counts` and the UI badges depending on overdue counts.
- When touching import steps (`views/imports.py`), keep `_save_step` consistent so `ImportJob.step_results` merges keys expected by the UI: parse (`import_date`, `sol_count`, `bq_count`, `as_count`, lifecycle counts, etc.), solicitations (`sols_created`, `sols_updated`), lines (`lines_created`, `lines_updated`, `as_loaded`), match (`matches_found`, `tier1`, `tier2`, `tier3`). The progress page also reads live JSON from each step response; `job.batch_id` / `job.import_date` are set on the `ImportJob` row.
- Changes to RFQ mailto actions require updating `sales/rfq/partials/mailto_buttons.html` (still used from RFQ pending and elsewhere — solicitation detail **Matches** tab no longer includes that partial).
- Updating `CompanyCAGE` defaults or email templates must preserve the “one default cage” invariant (`settings_cage_add/edit` resets others) so RFQ flows always find a markup rate or SMTP reply-to.

## 19. Quick Reference
- **Primary models:** `ImportBatch`, `Solicitation`/`SolicitationLine`, `SupplierMatch`, `SupplierRFQ`, `SupplierQuote`, `GovernmentBid`, `CompanyCAGE`, `EmailTemplate`, `RFQGreeting`, `RFQSalutation`, `NoQuoteCAGE`, `DibbsAward`, `DibbsAwardMod`, `AwardImportBatch`, `InboxMessage`, `InboxMessageRFQLink`, `SupplierNSN`/`SupplierFSC`, `ApprovedSource`.
- **Main URLs:** `/sales/import/*`, `/sales/awards/*` (list, wins report at `/sales/awards/wins/`, import, result), `/sales/solicitations/*`, `/sales/rfq/*` (including `supplier_create_and_queue` and Graph inbox under `rfq/inbox/`), `/sales/bids/*`, `/sales/suppliers/*`, `/sales/settings/*` (cages, email, greetings, salutations, **no-quote**), `/sales/settings/no-quote/`, `/sales/entity/cage/<cage_code>/` (`?fmt=json` supported).
- **Key templates:** `sales/import/progress.html`, `sales/solicitations/list.html`, `sales/solicitations/detail.html`, `sales/rfq/center.html`, `sales/rfq/inbox.html`, plus `rfq/partials/mailto_buttons.html`, `sales/bids/builder.html`, `sales/settings/email_templates.html`, `sales/settings/greetings.html`, `sales/settings/salutations.html`.
- **Key dependencies:** Playwright + Chromium (DIBBS fetch), `requests`/`BeautifulSoup` (DIBBS + SAM entity lookup), `SAM_API_KEY`, Django `DEFAULT_FROM_EMAIL`.
- **Risky files to review first:** `sales/services/importer.py`, `sales/services/matching.py`, `sales/services/bq_export.py`, `sales/views/imports.py`, `sales/views/rfq.py`.
