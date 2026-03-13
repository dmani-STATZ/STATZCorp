# DIBBS Sales App — Build Context

Django app (`sales`) for managing DIBBS solicitations, supplier matching, RFQ dispatch, bid building, and SAM.gov integration. SQL Server backend throughout — no Postgres-specific queries anywhere.

---

## Architecture Overview

### Key Models

| Model | Table | Purpose |
|---|---|---|
| `ImportBatch` | `tbl_ImportBatch` | Tracks each daily DIBBS file import |
| `ImportJob` | `tbl_ImportJob` | Tracks multi-step AJAX import in progress |
| `Solicitation` | `dibbs_solicitation` | One per solicitation; has `status`, `bucket`, `return_by_date` |
| `SolicitationLine` | `dibbs_solicitation_line` | NSN/line within a solicitation; has `bq_raw_columns` (JSONField) |
| `ApprovedSource` | `dibbs_approved_source` | NSN → approved CAGE → part number from AS file |
| `SupplierMatch` | — | Tier 1/2/3 matches between a line and a supplier |
| `SupplierRFQ` | — | RFQ sent to a supplier for a line |
| `SupplierQuote` | — | Quote received from a supplier |
| `SupplierContactLog` | — | Activity log per solicitation/supplier |
| `CompanyCAGE` | — | Our company CAGE settings (markup %, compliance codes, SMTP) |
| `GovernmentBid` | — | Bid built from a quote for BQ export |
| `DibbsAward` | `dibbs_award` | DLA award notices fetched from SAM.gov |
| `EmailTemplate` | `dibbs_email_template` | RFQ email subject/body templates with `{variable}` substitution; one can be `is_default` |
| `Supplier` (ad-hoc created) | `contracts_supplier` | Auto-created from SAM.gov lookup or stub; `[SAM]` prefix in notes = from SAM; `[STUB]` = manual fallback |

`Supplier` model lives in the `suppliers` app (`suppliers/models.py`, table `contracts_supplier`), field `cage_code`.

### Solicitation Status Flow
`New → Matching → RFQ_PENDING → RFQ_SENT → QUOTING → BID_READY → BID_SUBMITTED → WON / LOST / NO_BID`

### Triage Buckets
`UNSET → SDVOSB / HUBZONE / GROWTH / SKIP` — set automatically on import by `assign_triage_bucket()`, overridable manually in bulk from the list view.

### Set-Aside Codes
`R=SDVOSB, H=HUBZone, Y=Small Business, L=WOSB, A=8(a), E=EDWOSB, N=Unrestricted`

---

## Services

### `sales/services/importer.py`
Public entry point: `run_import(in_file, bq_file, as_file, imported_by)`.
Also exposes sub-functions for the AJAX import steps:
- `parse_dibbs_files()` — parses IN/BQ/AS files
- `create_import_batch()` — creates `ImportBatch`, clears old AS rows for same date
- `upsert_solicitations()` — bulk diff + create/update solicitations
- `upsert_lines_and_sources()` — bulk diff + create/update lines and AS rows

After matching, calls `sync_dla_awards()` (wrapped in try/except — import never fails due to awards sync).

### `sales/services/matching.py`
`run_matching_for_batch(batch_id)` — batch-queries all tiers upfront (~4 DB queries total regardless of import size):
- **Tier 1**: exact NSN match on `dibbs_supplier_nsn`
- **Tier 2**: approved CAGE from `ApprovedSource` → `Supplier.cage_code` lookup
- **Tier 3**: FSC match on `SupplierFSC`

Deduplicates by supplier (lowest tier wins). Skips item_type_indicator `'2'` for Tiers 1 & 2. Returns `{lines_processed, matches_found, by_tier: {1, 2, 3}}`.

`backfill_nsn_from_contracts(dry_run=False)` — backfills `SupplierNSN` from `contracts.Clin` history with recency weights (≤2y=1.0, ≤5y=0.6, ≤10y=0.3, else 0.1).

### `sales/services/suppliers.py`
`create_supplier_from_sam(sam_data, email='')` — find-or-create `Supplier` from `lookup_cage()` result; never overwrites existing. Notes prefixed `[SAM]`. Returns `(supplier, created)`.
`get_or_create_stub_supplier(cage_code, name, email, phone)` — fallback when SAM is down; notes prefixed `[STUB]`. Returns `(supplier, created)`.

### `sales/services/email.py`
`send_rfq_email()` and `send_followup_email()`. Resolves supplier email: contact FK → `primary_email` → `business_email`. Uses default `CompanyCAGE` for From/Reply-To.

### `sales/services/bq_export.py`
`generate_bq_file(bid_ids)` — overlays `GovernmentBid` fields onto `SolicitationLine.bq_raw_columns` (121-column BQ template). Raises `BQExportError` with `.errors` list on validation failure.

### `sales/services/sam_awards_sync.py`
`sync_dla_awards()` — fetches DLA award notices from SAM.gov Opportunities API v2. Paginates with `postedFrom=today−180d, postedTo=today−90d`. Returns `{created, updated, matched, won, errors}` or `{skipped, reason}` if no API key or 403. Matches awards to our `Solicitation` records and detects wins via `SAM_OUR_CAGE`.

### `sales/services/sam_entity.py`
`lookup_cage(cage_code)` — calls SAM.gov Entity Management API v3. Returns cleaned dict: `{found, cage_code, legal_name, uei, registration_status, registration_expiry, address, business_types, naics_codes, psc_codes, set_aside_flags, exclusion_status, sam_url}`. Returns `{found: False}` if no entity. Raises `ImproperlyConfigured` if `SAM_API_KEY` missing; raises `RequestException` with clear message on API errors. Set-aside flags parsed from `sbaBusinessTypeList`.

---

## Views

### `sales/views/imports.py`
- `import_upload` — validates form, saves files to temp dir, creates `ImportJob`, redirects to progress page
- `import_job_progress` — renders progress page
- `import_step_parse/solicitations/lines/match/awards` — 5 AJAX step endpoints (each returns JSON `{success, ...counts}`)
- `import_batch_delete` — deletes batch + `New` solicitations only (protects advanced statuses)
- `import_history` — paginated `ImportBatch` list with delete action
- `sync_awards_view` — staff-only POST; manually triggers `sync_dla_awards()`, returns JSON

### `sales/views/solicitations.py`
- `solicitation_list` — paginated, filterable (bucket, set_aside, status, q); bulk bucket reassignment via POST
- `solicitation_detail` — tabs: Overview, Matches, RFQs, Quotes, Bid; annotates `approved_sources` with `.matched_supplier` (one extra query via `Supplier.objects.filter(cage_code__in=...)`)
- `no_bid` — POST-only; sets status to `NO_BID`
- `global_search` — typeahead JSON (`fmt=json`) or full results page

### `sales/views/rfq.py`
`rfq_pending, rfq_sent, rfq_send_single, rfq_send_batch, rfq_mailto, rfq_mark_sent, rfq_center, rfq_center_detail, rfq_enter_quote, rfq_send_followup, rfq_mark_no_response, rfq_mark_declined, quote_select_for_bid, rfq_cage_preview, rfq_send_to_approved_source, rfq_send_to_adhoc`

RFQ Center (`/sales/rfq/center/`) is a 3-panel layout. `rfq_center_detail` returns an HTML fragment for `fetch()`. `rfq_enter_quote` returns JSON when called via AJAX.

**Manual RFQ email (mailto) flow:** `rfq_mailto(match_id)` — GET, returns JSON `{ mailto_url, to_email, subject, body }` or `{ missing_email: true }`; uses default `EmailTemplate` and supplier email (contact → primary_email → business_email). `rfq_mark_sent(match_id)` — POST; creates/updates `SupplierRFQ` (SENT), logs `SupplierContactLog` (EMAIL_OUT), advances solicitation to `RFQ_SENT` if needed; returns JSON for UI update. No SMTP; user opens email client and marks sent explicitly.

**Ad-hoc RFQ dispatch:** `rfq_cage_preview` — GET `?cage=XXXXX`, returns SAM.gov entity info + `already_in_db` flag; no DB writes. `rfq_send_to_approved_source` — POST; auto-creates `Supplier` from SAM (or stub fallback) for an `ApprovedSource` CAGE, creates `SupplierMatch` (tier 2, APPROVED_SOURCE), returns `mailto_url`. `rfq_send_to_adhoc` — POST; same flow for arbitrary CAGE input, creates `SupplierMatch` (tier 4, MANUAL).

### `sales/views/bids.py`
`bids_ready, bid_builder, bid_select_quote, bids_export_queue, bids_export_download, bids_history`

Export errors stored in `request.session['export_errors']` and shown on redirect. Download filename: `BQ_export_YYYY-MM-DD.txt`.

### `sales/views/suppliers.py`
`supplier_list, supplier_detail, supplier_add_nsn, supplier_add_fsc, supplier_remove_nsn, supplier_remove_fsc, backfill_nsn`

`backfill_nsn` is staff-only. NSN add: normalized to 13 digits, `source='manual'`, `match_score=100`.

### `sales/views/settings.py`
`settings_index, settings_cages, settings_cage_add, settings_cage_edit, email_template_list, email_template_edit, email_template_delete, email_template_set_default, email_template_preview`

Manages `CompanyCAGE` records and **Email Templates**. CAGE dropdowns use labeled choice helpers for SB codes, Affirmative Action, Previous Contracts, and ADR codes. Email templates: list (Name, Default, Updated, Actions), create/edit form with live preview (sample data + `_SafeDict` substitution), set default, delete (blocked for default); preview endpoint returns JSON `{ subject, body }` for debounced fetch.

### `sales/views/entity_lookup.py`
`entity_lookup(request, cage_code)` — `GET /sales/entity/cage/<cage_code>/`. Calls `lookup_cage()`, renders `entity_lookup.html`. Catches all exception types and passes an `error` string to the template — never raises a 500.

---

## Templates

| Template | Purpose |
|---|---|
| `sales/base.html` | Nav: Dashboard, Solicitations, RFQ Center (overdue badge), Bid Center, Suppliers, Import, Settings, Email Templates; topbar typeahead search |
| `sales/solicitations/list.html` | Bucket tab strip, filter bar, bulk reassignment toolbar + checkboxes |
| `sales/solicitations/detail.html` | Pipeline track; Overview tab (metadata + approved sources); Matches tab (approved sources with **Send RFQ** ACTION column + ad-hoc panel; matched suppliers with **Open RFQ Email** / **Mark Sent** mailto buttons); RFQs/Quotes/Bid tabs; activity feed |
| `sales/import/upload.html` | 3-file upload form only (processing moved to progress page) |
| `sales/import/progress.html` | 5-step AJAX progress: Parse → Solicitations → Lines → Match → Sync Awards; summary stat cards; staff "Sync Awards" button |
| `sales/import/history.html` | Paginated import batch list with delete |
| `sales/rfq/center.html` | 3-panel RFQ center |
| `sales/rfq/pending.html` | RFQ pending queue grouped by solicitation; each match has **Open RFQ Email** / **Mark Sent** (same mailto flow as detail Matches tab) |
| `sales/rfq/sent.html` | Sent RFQs grouped by urgency |
| `sales/rfq/quote_entry.html` | Quote entry with live suggested bid (JS) |
| `sales/bids/ready.html` | Lines with quotes ready to bid |
| `sales/bids/builder.html` | Bid builder (sections 01–06, live margin pill) |
| `sales/bids/export_queue.html` | BQ export queue |
| `sales/bids/history.html` | Submitted bid history; WON/LOST actions |
| `sales/suppliers/list.html` | Supplier list with search |
| `sales/suppliers/detail.html` | Tabs: Profile, Capabilities (NSN/FSC), Quote History |
| `sales/settings/cages.html` | CompanyCAGE list |
| `sales/settings/cage_form.html` | Add/edit CompanyCAGE |
| `sales/settings/email_templates.html` | Email template list (Name, Default, Updated, Set Default / Edit / Delete) |
| `sales/settings/email_template_form.html` | Create/edit template; two-column layout with live preview (fetch to `/sales/settings/email/preview/`) |
| `sales/rfq/partials/mailto_buttons.html` | Reusable partial: Open RFQ Email, Mark Sent, or ✓ Sent badge; used in detail Matches tab and RFQ pending |
| `sales/entity_lookup.html` | Read-only SAM.gov entity info card; 3 states: found / not-found / error |

---

## URLs (`sales/urls.py`, namespace `sales:`)

```
''                                          → dashboard
import/                                     → import_upload
import/history/                             → import_history
import/batch/<id>/delete/                   → import_batch_delete
import/job/<job_id>/                        → import_job_progress
import/job/<job_id>/step/parse/             → import_step_parse
import/job/<job_id>/step/solicitations/     → import_step_solicitations
import/job/<job_id>/step/lines/             → import_step_lines
import/job/<job_id>/step/match/             → import_step_match
import/job/<job_id>/step/awards/            → import_step_awards
solicitations/                              → solicitation_list
solicitations/<sol_number>/                 → solicitation_detail
solicitations/<sol_number>/nobid/           → no_bid
search/                                     → global_search
suppliers/backfill-nsn/                     → backfill_nsn
rfq/                                        → rfq_pending
rfq/center/                                 → rfq_center
rfq/center/<id>/detail/                     → rfq_center_detail
rfq/sent/                                   → rfq_sent
rfq/send/                                   → rfq_send_single
rfq/mailto/<match_id>/                      → rfq_mailto
rfq/<match_id>/mark-sent/                   → rfq_mark_sent
rfq/cage-preview/                           → rfq_cage_preview
rfq/send-to-approved-source/               → rfq_send_to_approved_source
rfq/send-to-adhoc/                         → rfq_send_to_adhoc
rfq/<sol_number>/send-batch/                → rfq_send_batch
rfq/<id>/quote/                             → rfq_enter_quote
rfq/<id>/followup/                          → rfq_send_followup
rfq/<id>/no-response/                       → rfq_mark_no_response
rfq/<id>/declined/                          → rfq_mark_declined
quotes/<id>/select-for-bid/                 → quote_select_for_bid
bids/                                       → bids_ready
bids/<sol_number>/build/                    → bid_builder
bids/select-quote/                          → bid_select_quote
bids/export/                                → bids_export_queue
bids/export/download/                       → bids_export_download
bids/history/                               → bids_history
suppliers/                                  → supplier_list
suppliers/<id>/                             → supplier_detail
suppliers/<id>/nsn/add/                     → supplier_add_nsn
suppliers/<id>/fsc/add/                     → supplier_add_fsc
suppliers/<id>/nsn/remove/                  → supplier_remove_nsn
suppliers/<id>/fsc/remove/                  → supplier_remove_fsc
settings/                                   → settings_index
settings/cages/                             → settings_cages
settings/cages/add/                         → settings_cage_add
settings/cages/<id>/edit/                   → settings_cage_edit
settings/email/                             → email_template_list
settings/email/new/                         → email_template_new
settings/email/<pk>/edit/                   → email_template_edit
settings/email/<pk>/delete/                 → email_template_delete
settings/email/<pk>/set-default/            → email_template_set_default
settings/email/preview/                     → email_template_preview
awards/sync/                                → sync_awards_view
entity/cage/<cage_code>/                    → entity_lookup
```

---

## Settings (`STATZWeb/settings.py`)

```python
SAM_API_KEY  = os.environ.get('SAM_API_KEY', '')   # SAM.gov API key — awards sync + entity lookup
SAM_OUR_CAGE = os.environ.get('SAM_OUR_CAGE', '')  # Our CAGE code — used to detect we_won on awards
# Context processor registered:
# 'sales.context_processors.rfq_counts'  →  overdue_rfq_count in all templates
```

---

## Migrations Applied

| Migration | What it adds |
|---|---|
| `0003_add_solicitation_bucket` | `bucket`, `bucket_assigned_by` on `Solicitation` |
| `0004_rfq_extra_fields_and_cage_smtp` | Extra `SupplierRFQ` fields; `smtp_reply_to` on `CompanyCAGE` |
| `0005_bq_raw_columns_and_bid_fields` | `bq_raw_columns` on `SolicitationLine`; extra `GovernmentBid` fields |
| `0006_add_hubzone_requested_by` | `hubzone_requested_by` on `Solicitation` |
| `0007_add_importjob` | `ImportJob` model |
| `0008_add_dibbs_award` | `DibbsAward` model |
| `0009_email_template` | `EmailTemplate` model (`dibbs_email_template`); seeds "Standard RFQ" default template |
| `0010_suppliermatch_manual_method` | Adds `MANUAL` choice to `SupplierMatch.match_method`; used for tier-4 ad-hoc matches |

---

## Key Design Decisions & Notes

- **AJAX import**: 5-step fetch() chain on `progress.html` — no WebSockets, no Celery. Each step is its own POST. `ImportJob._save_step()` must include `batch_id` and `import_date` in `update_fields` or they won't persist between requests.
- **Matching performance**: All tier queries are batched upfront (~4 queries total). Never query per-line.
- **BQ export**: Requires `SolicitationLine.bq_raw_columns` to be populated (needs BQ file at import time). Raises `BQExportError` otherwise.
- **Suggested bid**: `unit_price × (1 + default_markup_pct / 100)`; `default_markup_pct` from default `CompanyCAGE` (default 3.50).
- **Supplier email resolution**: contact FK → `primary_email` → `business_email`.
- **SAM.gov entity lookup**: Read-only, no DB writes. Uses same `SAM_API_KEY`. Graceful degradation on all error types — no 500s.
- **Approved sources — both Overview and Matches tabs**: `solicitation_detail` annotates each `ApprovedSource` with `.matched_supplier` via one `Supplier.objects.filter(cage_code__in=...)` query. Both the Overview tab and the Matches tab render the same logic: in-system CAGEs show a supplier link + "In system" green badge; unknown CAGEs show a "🔍 Lookup on SAM.gov" blue badge linking to `sales:entity_cage_lookup` in a new tab.
- **Tier 2 NSN normalization**: `ApprovedSource.nsn` stored without hyphens; query with `_normalize_nsn(line.nsn)`.
- **Archived suppliers**: Excluded from all matching tiers.
- **Manual RFQ email (mailto)**: No SMTP required. User clicks **Open RFQ Email** → GET `rfq_mailto/<match_id>/` returns `mailto_url` (or `missing_email`); client opens email app. User clicks **Mark Sent** → POST `rfq_mark_sent` creates/updates `SupplierRFQ` (SENT), logs contact, advances solicitation; UI replaces buttons with "✓ Sent" badge. Same pattern on Solicitation Detail Matches tab and RFQ Pending page. `sales/services/email.py` unchanged for future SMTP.

- **Ad-hoc RFQ dispatch**: `rfq_send_to_approved_source` and `rfq_send_to_adhoc` auto-create `Supplier` records. SAM hit → `[SAM]` notes; SAM miss → `[STUB]` notes. `_build_mailto_for_supplier()` is the shared helper. Tier-4 MANUAL matches are used for ad-hoc; tier-2 APPROVED_SOURCE for approved-source dispatches. Stub suppliers show INCOMPLETE badge in suppliers list.
- **SupplierMatch.match_method MANUAL**: Added in migration 0010. Tier 4 ad-hoc matches use this. Existing tiers 1/2/3 use DIRECT_NSN / APPROVED_SOURCE / FSC unchanged.

---

## Manual RFQ Email (Mailto) + Email Templates — Summary

- **Goal:** Staff can open a pre-filled RFQ in their email client and explicitly mark it sent, without SMTP.
- **Flow:** **Open RFQ Email** → JSON API builds `mailto:` URL from default `EmailTemplate` and supplier email (contact → primary_email → business_email). **Mark Sent** → POST creates/updates `SupplierRFQ` (SENT), `SupplierContactLog` (EMAIL_OUT), advances solicitation to `RFQ_SENT` when applicable; idempotent per (line, supplier).
- **Model:** `EmailTemplate` — name, subject_template, body_template, is_default, created_by; `render_subject(context)` / `render_body(context)` with `_SafeDict` (missing keys → empty string). Table `dibbs_email_template`; migration seeds "Standard RFQ".
- **Template variables:** `{supplier_name}`, `{sol_number}`, `{nsn}`, `{nomenclature}`, `{qty}`, `{unit_of_issue}`, `{return_date}`, `{your_name}`, `{your_email}`.
- **UI:** Reusable partial `sales/rfq/partials/mailto_buttons.html` in Matches tab and RFQ Pending; CSRF + JS (openMailto, markSent, showMatchAlert) on both pages. Settings → **Email Templates** in nav; list + create/edit with live preview (debounced fetch to preview endpoint).

---

## Future TODOs

### Bid Submission — Manual First, Batch as Luxury
- Batch quote/bid submission is a future enhancement; the manual single-bid flow must be solid first.
- **Bid Entry Screen (TBD):** When entering a bid, present a single screen showing everything the user needs to complete that bid. Data requirements for this screen still need to be collected before design can begin.
