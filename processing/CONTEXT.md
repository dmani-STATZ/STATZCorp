# processing Context

## 1. Purpose
`processing` is the staging and workflow app that buffers new contracts/CLINs coming from uploads or queue entries before they are materialized in the main `contracts` models. It owns the queue tables, the editable processing tables, the matching helpers, the CSV ingestion/export helpers, and the UI that lets an analyst match buyers/NSNs/suppliers, adjust splits, and finalize the canonical `Contract`/`Clin` records.

## 2. App Identity
- **Django app label:** `processing`
- **AppConfig:** `ProcessingConfig` (`processing/apps.py`)
- **Filesystem path:** `processing/` inside the repo root
- **Role:** Support/back-office workflow app – bridges import queue data with enterprise contracts and orchestrates the UI/API for manual validation and finalization.

## 3. High-Level Responsibilities
- Collect raw contract/CLIN payloads in `QueueContract`/`QueueClin`, expose a queue UI, and guard concurrent processing via `initiate_processing`/`start_processing`.
- Provide editable processing records (`ProcessContract`/`ProcessClin`/`ProcessClinSplit`) with calculated values, per-CLIN split management, and matching to canonical `contracts`, `products`, and `suppliers` data.
- Drive the contract-to-contract workflow via views (`processing_views.*`), API endpoints, and forms so users can save drafts, mark ready, finalize, or cancel without touching the live data until validation succeeds.
- Offer CSV tooling (template download, test data, upload) to bulk-import queue items, with dedup checks against `Contract` and `QueueContract`.
- Offer DD Form 1155 award **PDF** upload on the queue page (`upload_award_pdf` → `parse_award_pdf` / `ingest_parsed_award` in `processing/services/pdf_parser.py`), with queue PDF status columns and parse-notes UI.
- Track sequence numbers for PO/Tab assignment (`SequenceNumber`) and expose management helpers (e.g., `get_next_numbers`, `save_contract`) that power the JavaScript heavy UI.

## 4. Key Files and What They Do
| File | Role |
| --- | --- |
| `models.py` | Defines queue + processing tables: `QueueContract/QueueClin` for raw payloads, `ProcessContract/ProcessClin/ProcessClinSplit` for the editable workflow, `SequenceNumber` for PO/Tab generation, and helper methods (`calculate_contract_value`, split classmethods). |
| `forms.py` | `ProcessContractForm` persists per-CLIN split POST keys (`clin-<id>-splits-...`); `ProcessClinForm` auto-calculates values and exposes widgets; `ProcessClinFormSet` lets the template edit many CLINs inline. |
| `views/processing_views.py` | Core HTTP handlers for queue presentation, starting processing, matching helpers, saving drafts, finalizing contracts (including `PaymentHistory` and `ClinSplit` creation per finalized CLIN), cancellation, CSV import/export, award PDF upload (`upload_award_pdf`), SharePoint stub (`save_to_sharepoint`), and helper APIs consumed by the template. |
| `views/api_views.py` | AJAX-friendly endpoints for the UI to sync individual fields, add/delete CLINs, recalc values, and bulk save CLIN details outside the Django formset cycle. |
| `views/matching_views.py` | Legacy-style POST search helpers (older signatures); the live contract form’s NSN/supplier modals primarily use `contracts` API search + `processing_views.match_*` for POST match-by-ID. |
| `urls.py` | Maps queue, processing, matching, API, CSV/PDF upload, and per-CLIN split routes (`/queue/`, `/contract/<pk>/edit/`, `/match-*`, `/api/*`, `/upload/`, `/upload-award-pdf/`, `/clin/<id>/splits/...`). |
| `templates/processing/*.html` | `contract_queue.html` renders the queue table/controls (including PDF parse status column and parse-notes modal), `process_contract_form.html` is the form-heavy edit page, `process_contract_detail.html` shows readonly state, and `modals/*` hold buyer/IDIQ/NSN/supplier pickers plus `pdf_parse_notes_modal.html`. |
| `static/processing/js/*.js` | Client-side scripts (`process_contract.js`, `*_modal.js`) handle asynchronous saves, modal wiring, numeric recalculations, split manipulation, and match dialogs mentioned in templates. |
| `docs/*.md` | Implementation notes (`API_DOCUMENTATION.md`, workflow guide, split implementation notes, IDIQ modularization) document the intent behind the workflow and highlight future work. |
| `admin.py` | Registers only `QueueContract` with a read-only view and a force-delete action that cascades through queue/processing records. |
| `services/pdf_parser.py` | Standalone award PDF parsing (`parse_award_pdf`) and queue upsert (`ingest_parsed_award`); no view/HTTP imports. |
| `services/contract_utils.py` | Shared pure-Python helpers for DLA contract numbers and NSN normalization (`normalize_contract_number`, `detect_contract_type`, `normalize_nsn`); no Django model imports. |

## 5. Data Model / Domain Objects
- `QueueContract`/`QueueClin` mirror incoming CSV or queue inputs with text fields for buyer/NSN/supplier and status flags (`is_being_processed`, `matched_*`). `QueueContract` also stores award-PDF ingestion metadata: `pdf_parse_status` (`pending` / `success` / `partial`), `pdf_parsed_at`, and `pdf_parse_notes`. They inherit `AuditModel` from `contracts` and default to `Company.get_default_company` when `company_id` is missing.
- `SequenceNumber` stores the shared PO/Tab counters; UI flows call `advance_po_number`/`advance_tab_number` when creating new processing contracts and finalizers ensure the counters stay ahead of the last assigned values.
- `ProcessContract` wraps `Contract` metadata plus staging fields (`buyer_text`, `contract_type_text`, `sales_class_text`, `plan_gross`, `planned_split`, `final_contract`). Status choices (`draft` → `completed`) track workflow state. Key methods: `calculate_contract_value`, `calculate_plan_gross`, and `update_calculated_values`, which power the `update_contract_values` API and ensure `contract_value`/`plan_gross` reflect CLIN totals. **`total_split_value` / `total_split_paid`** on `ProcessContract` are computed aggregates over all `ProcessClinSplit` rows for its CLINs (not stored columns on `ProcessContract`).
- `ProcessClin` mirrors `Clin` with foreign keys to `Supplier`, `Nsn`, `ClinType`, `SpecialPaymentTerms`, text backups (`nsn_text`, `supplier_text`), numeric fields used by the form to recompute `item_value`/`quote_value`, and late/dates/supplier due flags. `final_clin` links to the canonical `Clin` once finalized.
- `ProcessClinSplit` holds split allocations per **process CLIN** (FK to `ProcessClin`, CASCADE, related name `splits`); classmethods `create_split`, `update_split`, and `delete_split` support the AJAX and form POST flows.

## 6. Request / User Flow
1. **Queue intake:** `/processing/upload/` ingests CSV rows into `QueueContract`/`QueueClin`, skipping duplicates already in `Contract` or `QueueContract`. `/processing/upload-award-pdf/` (`upload_award_pdf`) accepts multipart `pdf_files`, parses each DD Form 1155 PDF, calls `ingest_parsed_award`, then invokes the no-op `save_to_sharepoint` stub (future Microsoft Graph hook). `download-template` and `download-test-data` supply CSV scaffolding/test payloads (with test download limited to `DEBUG` mode).
2. **Queue dashboard:** `ContractQueueListView` (`/processing/queue/`) lists queue items, counts CLIN totals per contract, shows PDF parse status per row, and offers buttons wired to start/cancel actions. The drop zone accepts CSV and PDF; CSV still posts to `/processing/upload/` only. `QueueContract.contract_type` is set at intake from `detect_contract_type()` (DLA position-9 map) when possible, with CSV column text as fallback on CSV upload; values include `'IDIQ'`, `'DO'`, `'PO'`, `'AWD'`, `'MOD'`, `'AMD'`, `'INTERNAL'`, or unset (null/blank). The queue table shows a **Type** badge column per row (including PO/MOD/AMD/INTERNAL). Debug context includes `contract_type` on the first queue row sample. `start_processing` returns `redirect_url` for IDIQ contracts so the client can open the IDIQ editor; queue-page JavaScript uses that URL when present and otherwise falls back to the standard process-contract edit URL.
3. **Start processing:** `initiate_processing` marks `QueueContract` as locked, `start_processing` clones queue data into `ProcessContract`/`ProcessClin`, uses `SequenceNumber` to mint PO/Tab, and flags the queue item as in-progress. `start_new_contract` can create a blank process contract + a default CLIN without queue data.
4. **Editing:** `/processing/contract/<pk>/edit/` renders `ProcessContractForm` + `ProcessClinFormSet` with JS-assisted modals (`buyer`, `NSN`, `supplier`, `IDIQ`). `ProcessContractUpdateView` passes `pdf_parse_status`, `pdf_parse_notes`, and `queue_contract` (from `ProcessContract.queue_id`) so analysts can open parse notes when status is `partial`. Clients hit AJAX endpoints (`save_contract`, `update_clin_field`, `update_process_contract_field`, `save_clin`, etc.) as fields change, and `process_contract.js` orchestrates instantaneous saves, recalculations, and status badge updates.
5. **Matching:** `match_buyer` and `match_idiq` remain POST-only for their flows. `match_nsn` and `match_supplier` (in `processing_views.py`) accept **GET** `?action=search&q=…` for up to 20 `Nsn` / `Supplier` rows (`{results: [...]}`), **POST** `{id: …}` or `{supplier_id: …}` to attach an existing record, and **POST** `{action: 'create', …}` to create a new `Nsn` or `Supplier` and link it to the `ProcessClin`. The standard contract modals still use POST match-by-ID (`id` for NSN, `supplier_id` for supplier) and separate `contracts` APIs for search/create; **`idiq_processing_edit.html`** uses self-contained inline modals that call the extended `match_nsn` / `match_supplier` endpoints for search, select, and create in one place.
6. **Splits:** Per-CLIN splits are edited in the process form (and persisted via `clin-<clin_id>-splits-...` POST keys). AJAX routes under `/clin/.../splits/` add/update/delete or run **Calc Splits** (STATZ = item_value − quote_value, floored at zero). `save_contract` also runs `persist_clin_splits_for_contract` so a full FormData save updates `ProcessClinSplit` rows.
7. **Finalization:** `/contract/<process_contract_id>/finalize/` (and `finalize_and_email_contract`) validate buyer/NSN/supplier presence, create `Contract`, `Clin`, **`ClinSplit` rows (one per `ProcessClinSplit` on each `ProcessClin`, scoped to the new `Clin`)**, and `PaymentHistory` records, update `SequenceNumber`, set `ProcessClin.final_clin` before delete, and remove queue/process records (optionally building a `mailto:` URL in the email path). `mark_ready_for_review` bumps status and keeps the queue item locked for reviewers.
8. **Cancellation:** `/process-contract/<pk>/cancel/` or `cancel_processing` roll back queue locks; `cancel_process_contract` also deletes the `ProcessContract` while resetting `QueueContract` flags.

## 7. Templates and UI Surface Area
- `processing/templates/processing/contract_queue.html` renders the queue list, contract **Type** badges (IDIQ/DO/AWD/PO/MOD/AMD/INTERNAL and a generic badge for any other non-blank `contract_type`), processing status, **PDF** column (pending/success/partial icons; partial opens parse notes modal), drag/drop for CSV and PDF, and buttons that call `/start-processing/`, `/start-new-contract/`, or `/cancel-processing/`. The view computes counts (total CLINs, processing count, debug info for first contract, including `contract_type` on the sample row).
- `process_contract_form.html` (extends `contracts/contract_base.html`) contains a grid of contract fields, status card, CLIN table, split management UI, and system message region. Buttons/inputs call `saveContract()`/`process_contract.js` to hit `/save-contract/`, match modals, and toggle read-only states. The template also loads the modals under `templates/processing/modals/` for buyer/IDIQ/NSN/supplier lookups.
- `process_contract_detail.html` displays the contract summary and connected CLINs for readonly review.
- JS assets (`process_contract.js`, `*_modal.js`, plus placeholder `clin_handling.js`) supply the interactive behavior (AJAX saves, match modal wiring, validation, split row updates).
- UI is server-rendered but heavily augmented with AJAX and modal dialogs; there is no SPA but the form relentlessly hits `save_contract`/API endpoints to persist edits without full form submission.

## 8. Admin / Staff Functionality
- `QueueContract` and `ProcessClinSplit` are registered (`ProcessClinSplit` is a small staff-facing view). The queue view is read-only except for the custom `force_delete_contracts` action, which deletes related `QueueClin`, `ProcessContract`, `ProcessClin` (CASCADE drops `ProcessClinSplit` rows), inside a transaction.
- Staff rarely edit models directly; the admin acts as a cleanup tool for stuck queue items.

## 9. Forms, Validation, and Input Handling
- `ProcessContractForm` calls `persist_clin_splits_for_contract` on `save` so `clin-<clin_id>-splits-<split_id|new n>-<field>` keys create/update/delete `ProcessClinSplit` rows. It still updates `contract_type_text`/`sales_class_text` on the `ProcessContract` as before.
- `ProcessClinForm` enforces calculations in `clean()` so `item_value` and `quote_value` derive from `order_qty` × `unit_price` / `price_per_unit`. Widgets make some inputs readonly.
- `ProcessClinFormSet` (inline formset) manages multiple CLIN rows using `ProcessClin` fields; `ProcessContractUpdateView` injects this formset into the template so each CLIN can be edited together with the parent contract.
- Additional AJAX endpoints (`update_clin_field`, `save_clin`, `update_process_contract_field`) revalidate/parse values server-side (dates, decimals, booleans) before saving; protected fields (buyer/NSN/supplier) can only be updated via matching endpoints.

## 10. Business Logic and Services
- `processing_views` contains the scenario logic: `start_processing` clones queue data, `finalize_contract`/`finalize_and_email_contract` build final `Contract`/`Clin`/`ClinSplit`/`PaymentHistory` and drop the processing records, `cancel_process_contract` resets queue locks, `save_and_return_to_queue` inspects form/formset validity, and `upload_csv` parses rows with strict column/duplicate/date/decimal validation before creating `QueueContract`/`QueueClin`.
- **`services/contract_utils.py`:** Shared utility module with no Django model dependencies. **`normalize_contract_number(s)`** normalizes DLA contract numbers to dashed format; unknown formats pass through with a warning. **`detect_contract_type(s)`** reads the position-9 character of a normalized DLA contract number (the single-character segment between the second and third hyphens) and returns the internal type label: `'IDIQ'`, `'DO'`, `'PO'`, `'AWD'`, `'MOD'`, `'AMD'`, `'INTERNAL'`, or `None`. Type character map: D=IDIQ, F=DO, P/V=PO, C=AWD, M=MOD, A=AMD, N=INTERNAL. **`normalize_nsn(s)`** normalizes NSN strings to hyphenated form; S-codes pass through unchanged. All three are pure Python with no ORM side effects, safe from any ingestion path. `pdf_parser.py` delegates `_normalize_nsn` to this module. `upload_csv` and `sales/services/queue_we_won_awards.py` call `detect_contract_type` when creating `QueueContract` rows.
- `upload_award_pdf` validates `.pdf` extensions, calls `parse_award_pdf` and `ingest_parsed_award` (from `processing.services.pdf_parser`) inside per-file `transaction.atomic()` blocks, returns JSON `results` per file, and calls `save_to_sharepoint` (no-op logger stub) after each successful ingestion for a future SharePoint/Microsoft Graph integration.
- `pdf_parser.py` implements `parse_award_pdf` and `ingest_parsed_award`. Key behaviors: Section B is extracted precisely using `_section_b_slice()` — finds first SECTION B header, stops at the next SECTION X header (any letter except B), sends the full extracted text to the Claude API with no character truncation. Two CLIN table formats handled: Variant 2 (DLA Maritime/Land — CLIN PR PRLI UI header, NSN/MATERIAL: line, DELIVER BY: keyword, e.g. SPE7M3 contracts) and Variant 1 (DLA Aviation — ITEM NO. SUPPLIES/SERVICES header, inline NSN, CAGE/PN: supplier line, DELIVERY DATE: keyword, e.g. SPE4A7 contracts). Per-CLIN supplier is extracted from CAGE/PN: cage code within each CLIN block; falls back to Block 9 contractor cage only when not present. Block 9 is always STATZ (the contractor/distributor) — never the actual supplier. DLA S-codes (e.g. S00000053) are FAT/PLT service CLINs — stored as-is in the NSN field, description extracted from the plain English label preceding the CLIN row (e.g. 'Contractor First Article Test'). Contract due date = award_date + ado_days when ADO present in Block 10; falls back to latest CLIN due date when Block 10 says 'SEE SCHEDULE' or similar. `uom` is copied from `QueueClin` to `ProcessClin` in `start_processing` — if new fields are added to `QueueClin` they must be explicitly added to the `ProcessClin.objects.create()` call or they will be silently dropped.
- `SequenceNumber` ensures PO/Tab uniqueness across the workflow and is consulted/advanced before new contracts are created or finalization ensures the counter stays ahead.
- `ProcessContract.calculate_contract_value`, `calculate_plan_gross`, and `update_calculated_values` are used when `update_contract_values` runs (no automatic STATZ process-split creation there).
- `ProcessClinSplit` classmethods are used for AJAX; form persistence is centralized in `persist_clin_splits_for_contract`.
- API helpers (`api_views`) support adding CLIN clones (copying CLIN `0001`), updating individual fields with conversions, deleting CLINs, saving entire CLIN payloads in `save_clin`, and `update_contract_values` to refresh contract / plan gross from CLINs.

## 11. Integrations and Cross-App Dependencies
- Imports from `contracts.models` (`Contract`, `Clin`, `ClinSplit`, `Buyer`, `IdiqContract`, `ClinType`, `SpecialPaymentTerms`, `ContractType`, `SalesClass`, `PaymentHistory`, `ContractStatus`) show that `processing` writes the final authoritative records back into the `contracts` app and references the same lookup tables.
- `products.models.Nsn` and `suppliers.models.Supplier` supply NSN and supplier FK targets for `ProcessClin`.
- `QueueContract`/`QueueClin` use `AuditModel` and `Company`, linking them to the shared company/metadata stored in `contracts`.
- Views like `match_buyer`/`match_nsn`/`match_supplier` query their respective models and expect IDs from modals generated with JS templates, so renaming those lookups requires coordination across the `processing/static` JS and `templates`.
- Staging `ProcessClinSplit` data is materialized to `contracts.ClinSplit` per canonical `Clin` when finalizing. `PaymentHistory` entries created during finalization use the `ContentType` framework tied to `contracts`.

## 12. URL Surface / API Surface
- **Queue + batch:** `/processing/queue/`, `/processing/start-new-contract/`, `/processing/start-processing/<queue_id>/`, `/processing/get-next-numbers/`, `/processing/upload/`, `/processing/upload-award-pdf/` (`processing:upload_award_pdf`), `/processing/download-template/`, `/processing/download-test-data/`.
- **Processing contract UI:** `/processing/contract/<pk>/`, `/processing/contract/<pk>/edit/`, `/processing/contract/<id>/save/`, `/processing/contract/<id>/finalize/`, `/processing/contract/<id>/finalize-and-email/`, `/processing/process-contract/<id>/cancel/`, `/processing/process-contract/<id>/mark-ready/`.
- **Matching endpoints:** `/processing/match-buyer/<id>/`, `/processing/match-nsn/<process_clin_id>/` (GET search + POST match/create), `/processing/match-supplier/<process_clin_id>/` (same), `/processing/match-idiq/<id>/`.
- **AJAX/API:** `/processing/api/...` handles GET/PUT for processing contracts, create/update/delete CLINs, update single fields, `save_clin`, and `update_contract_values`.
- **CLIN splits:** `/processing/clin/<clin_pk>/splits/add/`, `/processing/clin/splits/<split_pk>/update/`, `/processing/clin/splits/<split_pk>/delete/`, `/processing/clin/<clin_pk>/splits/calc/`.
- **Admin-like actions:** `/processing/queue/delete/<queue_id>/` (superusers only), `/processing/contract/<pk>/save/`, `/processing/save-contract/` (duplicate alias).

## 13. Permissions / Security Considerations
- `@login_required` decorates every view in `processing_views.py`, `api_views.py`, and `matching_views.py`; anonymous traffic cannot access the workflow.
- `delete_queue_contract` explicitly enforces `request.user.is_superuser`.
- `download_test_data` immediately raises `PermissionDenied` if `settings.DEBUG` is `False`.
- Finalization views require matched buyer/NSN/supplier FKs (`finalize_contract` returns errors if they are absent), so workflow fails fast when data is incomplete.
- `start_processing`/`initiate_processing` use `select_for_update`/atomic transactions so two users cannot claim the same queue record.
- `QueueContractAdmin` makes the admin view read-only and only exposes a safest `force_delete_contracts` action; the normal add/change buttons are blocked.
- APIs like `update_clin_field` protect `nsn`/`supplier` fields, requiring the matching endpoints to populate them.

## 14. Background Processing / Scheduled Work
- No Celery or cron-like jobs are defined inside this app; every operation is triggered by HTTP endpoints. `upload_csv` handles long-running CSV parsing synchronously inside a transaction.

## 15. Testing Coverage
- `processing/tests.py` is empty (`# Create your tests here.`).
- There are no unit tests, API tests, or integration tests covering models, views, or forms in this app.

## 16. Migrations / Schema Notes
- `migrations/0001_initial.py` introduced the core tables; later migrations add queue PDF fields, company FKs, and (as of `0019`) replace contract-level process splits with `ProcessClinSplit` and `ClinSplit` in the contracts app.
- Migration `0012` adds `company` fields to `ProcessClin`/`ProcessContract`, suggesting a cleanup to track company ownership.
- Migration `0013` adjusted `nsn`/`supplier` FKs, showing this schema mutates when the supplier/NSN relationships need stricter validation.
- Later migrations add `QueueContract` PDF ingestion fields (`pdf_parse_status`, `pdf_parsed_at`, `pdf_parse_notes`) and related indexes/defaults as needed.

## 17. Known Gaps / Ambiguities
- Entire app lacks tests (no coverage for matching logic, CSV ingestion, finalization, or form handling).
- Per-CLIN split UI is driven by `process_contract.js` and the `clin-…-splits-…` input names; `save_contract` and `ProcessContractForm.save` must stay aligned with `persist_clin_splits_for_contract`.
- `matching_views` stubs use different URL signatures than the wired `processing_views` match endpoints; prefer `processing_views.match_nsn` / `match_supplier` for authoritative behavior (including IDIQ inline modals). Create-new for NSN/supplier on the main process form still flows through `contracts` APIs where applicable.
- The `save_contract` and `save_clin` endpoints log a lot of `print`/`logger.debug` statements, indicating debugging is still active; expect noise and potential secrets logged in console output during heavy usage.

## 18. Safe Modification Guidance for Future Developers / AI Agents
1. Keep queue/process syncing intact — renaming `QueueContract`/`QueueClin` fields requires updates to both `start_processing`, `upload_csv`, and the templates with matching form names.
2. When adjusting match logic, update both the modal templates (`processing/templates/processing/modals/*.html`), JS (`static/processing/js/*_modal.js`), and the POST-handling views (`match_*` in `processing_views.py` and `matching_views.py`).
3. If you rename `ProcessClinSplit` or change POST key patterns, keep `persist_clin_splits_for_contract`, the template inputs, and `finalize_*` `ClinSplit` creation aligned.
4. Any change to `confirm` finalization (e.g., adding validations) must keep `PaymentHistory` creation and queue/the sequence handling in sync so PO/Tab counters and completed contracts remain consistent.
5. Re-run `processing_views.upload_csv` logic and the dedup/validation loops when altering columns; the view relies on exact CSV headers and will break quietly if names change.
6. Keep `pdf_parser.py` free of HTTP/view coupling; extend parsing or ingestion there and wire new behavior from `upload_award_pdf` (or similar orchestration) only.

## 19. Quick Reference
- **Primary models:** `QueueContract`, `QueueClin`, `ProcessContract`, `ProcessClin`, `ProcessClinSplit`, `SequenceNumber`.
- **Main URLs:** `/processing/queue/`, `/processing/contract/<pk>/edit/`, `/processing/start-processing/<queue_id>/`, `/processing/contract/<id>/finalize/`, `/processing/upload/`, `/processing/upload-award-pdf/`, `/processing/api/processing/<id>/...`.
- **Key templates:** `processing/contract_queue.html`, `processing/process_contract_form.html`, `processing/process_contract_detail.html`, plus modals under `processing/modals/` (including `pdf_parse_notes_modal.html`).
- **Key dependencies:** `contracts` (Contract/Clin/ClinSplit/.../PaymentHistory), `products.Nsn`, `suppliers.Supplier`, shared `Company` model.
- **Risky files:** `views/processing_views.py` (central workflow, finalization, CSV import), `forms.py` (split persistence), `static/processing/js/process_contract.js` (AJAX state machine), `processing/models.py` (schema/SequenceNumber), and the large templates that must stay aligned with API payloads.


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
