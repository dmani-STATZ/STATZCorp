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
- Provide editable processing records (`ProcessContract`/`ProcessClin`/`ProcessContractSplit`) with calculated values, split management, and matching to canonical `contracts`, `products`, and `suppliers` data.
- Drive the contract-to-contract workflow via views (`processing_views.*`), API endpoints, and forms so users can save drafts, mark ready, finalize, or cancel without touching the live data until validation succeeds.
- Offer CSV tooling (template download, test data, upload) to bulk-import queue items, with dedup checks against `Contract` and `QueueContract`.
- Track sequence numbers for PO/Tab assignment (`SequenceNumber`) and expose management helpers (e.g., `get_next_numbers`, `save_contract`) that power the JavaScript heavy UI.

## 4. Key Files and What They Do
| File | Role |
| --- | --- |
| `models.py` | Defines queue + processing tables: `QueueContract/QueueClin` for raw payloads, `ProcessContract/ProcessClin/ProcessContractSplit` for the editable workflow, `SequenceNumber` for PO/Tab generation, and helper methods (`calculate_contract_value`, split classmethods). |
| `forms.py` | `ProcessContractForm` wires contract/split widgets and persists split rows; `ProcessClinForm` auto-calculates values and exposes widgets; `ProcessClinFormSet` lets the template edit many CLINs inline. |
| `views/processing_views.py` | Core HTTP handlers for queue presentation, starting processing, matching helpers, saving drafts, finalizing contracts (including `PaymentHistory`/`ContractSplit` creation), cancellation, CSV import/export, and helper APIs consumed by the template. |
| `views/api_views.py` | AJAX-friendly endpoints for the UI to sync individual fields, add/delete CLINs, recalc values, and bulk save CLIN details outside the Django formset cycle. |
| `views/matching_views.py` | Lightweight search endpoints that look up buyers/NSNs/suppliers by partial text to populate modals used in the form. |
| `urls.py` | Maps queue, processing, matching, API, CSV, and split-management routes (`/queue/`, `/contract/<pk>/edit/`, `/match-*`, `/api/*`, `/upload/`, `/contract/split/*`). |
| `templates/processing/*.html` | `contract_queue.html` renders the queue table/controls, `process_contract_form.html` is the form-heavy edit page, `process_contract_detail.html` shows readonly state, and `modals/*` hold buyer/IDIQ/NSN/supplier pickers. |
| `static/processing/js/*.js` | Client-side scripts (`process_contract.js`, `*_modal.js`) handle asynchronous saves, modal wiring, numeric recalculations, split manipulation, and match dialogs mentioned in templates. |
| `docs/*.md` | Implementation notes (`API_DOCUMENTATION.md`, workflow guide, split implementation notes, IDIQ modularization) document the intent behind the workflow and highlight future work. |
| `admin.py` | Registers only `QueueContract` with a read-only view and a force-delete action that cascades through queue/processing records. |

## 5. Data Model / Domain Objects
- `QueueContract`/`QueueClin` mirror incoming CSV or queue inputs with text fields for buyer/NSN/supplier and status flags (`is_being_processed`, `matched_*`). They inherit `AuditModel` from `contracts` and default to `Company.get_default_company` when `company_id` is missing.
- `SequenceNumber` stores the shared PO/Tab counters; UI flows call `advance_po_number`/`advance_tab_number` when creating new processing contracts and finalizers ensure the counters stay ahead of the last assigned values.
- `ProcessContract` wraps `Contract` metadata plus staging fields (`buyer_text`, `contract_type_text`, `sales_class_text`, `plan_gross`, `planned_split`, `final_contract`). Status choices (`draft` → `completed`) track workflow state. Key methods: `calculate_contract_value`, `calculate_plan_gross`, and `update_calculated_values`, which power the `update_contract_values` API and ensure `contract_value`/`plan_gross` reflect CLIN totals.
- `ProcessClin` mirrors `Clin` with foreign keys to `Supplier`, `Nsn`, `ClinType`, `SpecialPaymentTerms`, text backups (`nsn_text`, `supplier_text`), numeric fields used by the form to recompute `item_value`/`quote_value`, and late/dates/supplier due flags. `final_clin` links to the canonical `Clin` once finalized.
- `ProcessContractSplit` holds dynamic split allocations per contract; helper classmethods (`create_split`, `update_split`, `delete_split`) plus the formset wiring keep sums tracked and allow JS to append new rows.

## 6. Request / User Flow
1. **Queue intake:** `/processing/upload/` ingests CSV rows into `QueueContract`/`QueueClin`, skipping duplicates already in `Contract` or `QueueContract`. `download-template` and `download-test-data` supply CSV scaffolding/test payloads (with test download limited to `DEBUG` mode).
2. **Queue dashboard:** `ContractQueueListView` (`/processing/queue/`) lists queue items, counts CLIN totals per contract, and offers buttons wired to start/cancel actions.
3. **Start processing:** `initiate_processing` marks `QueueContract` as locked, `start_processing` clones queue data into `ProcessContract`/`ProcessClin`, uses `SequenceNumber` to mint PO/Tab, and flags the queue item as in-progress. `start_new_contract` can create a blank process contract + a default CLIN without queue data.
4. **Editing:** `/processing/contract/<pk>/edit/` renders `ProcessContractForm` + `ProcessClinFormSet` with JS-assisted modals (`buyer`, `NSN`, `supplier`, `IDIQ`). Clients hit AJAX endpoints (`save_contract`, `update_clin_field`, `update_process_contract_field`, `save_clin`, etc.) as fields change, and `process_contract.js` orchestrates instantaneous saves, recalculations, and status badge updates.
5. **Matching:** Separate POST endpoints (`match_buyer`, `match_nsn`, `match_supplier`, `match_idiq`) accept IDs from modal pickers and update the FK/text fields on `ProcessContract`/`ProcessClin`.
6. **Splits:** Split creation/update/delete happen via `/contract/split/*` views or through the form’s `splits-...` payload handling in `ProcessContractForm.save`.
7. **Finalization:** `/contract/<process_contract_id>/finalize/` (and the more elaborate `finalize_and_email_contract`) validates buyer/NSN/supplier presence, creates `Contract`, `Clin`, `ContractSplit`, and `PaymentHistory` records, updates `SequenceNumber`, deletes the queue/process entries, and optionally builds a `mailto:` URL. `mark_ready_for_review` bumps status and keeps the queue item locked for reviewers.
8. **Cancellation:** `/process-contract/<pk>/cancel/` or `cancel_processing` roll back queue locks; `cancel_process_contract` also deletes the `ProcessContract` while resetting `QueueContract` flags.

## 7. Templates and UI Surface Area
- `processing/templates/processing/contract_queue.html` renders the queue list, statuses, and buttons that call `/start-processing/`, `/start-new-contract/`, or `/cancel-processing/`. The view computes counts (total CLINs, processing count, debug info for first contract).
- `process_contract_form.html` (extends `contracts/contract_base.html`) contains a grid of contract fields, status card, CLIN table, split management UI, and system message region. Buttons/inputs call `saveContract()`/`process_contract.js` to hit `/save-contract/`, match modals, and toggle read-only states. The template also loads the modals under `templates/processing/modals/` for buyer/IDIQ/NSN/supplier lookups.
- `process_contract_detail.html` displays the contract summary and connected CLINs for readonly review.
- JS assets (`process_contract.js`, `*_modal.js`, plus placeholder `clin_handling.js`) supply the interactive behavior (AJAX saves, match modal wiring, validation, split row updates).
- UI is server-rendered but heavily augmented with AJAX and modal dialogs; there is no SPA but the form relentlessly hits `save_contract`/API endpoints to persist edits without full form submission.

## 8. Admin / Staff Functionality
- Only `QueueContract` is registered (`admin.QueueContractAdmin`). The admin view is read-only (`has_add_permission`/`has_change_permission` return `False`) except for the custom `force_delete_contracts` action, which deletes related `QueueClin`, `ProcessContract`, `ProcessClin`, and `ProcessContractSplit` records inside a transaction.
- Staff rarely edit models directly; the admin acts as a cleanup tool for stuck queue items.

## 9. Forms, Validation, and Input Handling
- `ProcessContractForm` wires contract fields, readonly text fields, and `splits` payload processing. During `save`, it updates `contract_type_text`/`sales_class_text` and deletes or creates `ProcessContractSplit` rows according to `splits-<id>-<field>` POST keys.
- `ProcessClinForm` enforces calculations in `clean()` so `item_value` and `quote_value` derive from `order_qty` × `unit_price` / `price_per_unit`. Widgets make some inputs readonly.
- `ProcessClinFormSet` (inline formset) manages multiple CLIN rows using `ProcessClin` fields; `ProcessContractUpdateView` injects this formset into the template so each CLIN can be edited together with the parent contract.
- Additional AJAX endpoints (`update_clin_field`, `save_clin`, `update_process_contract_field`) revalidate/parse values server-side (dates, decimals, booleans) before saving; protected fields (buyer/NSN/supplier) can only be updated via matching endpoints.

## 10. Business Logic and Services
- `processing_views` contains the scenario logic: `start_processing` clones queue data, `finalize_contract`/`finalize_and_email_contract` build final `Contract`/`Clin`/`PaymentHistory`/`ContractSplit` and drop the processing records, `cancel_process_contract` resets queue locks, `save_and_return_to_queue` inspects form/formset validity, and `upload_csv` parses rows with strict column/duplicate/date/decimal validation before creating `QueueContract`/`QueueClin`.
- `SequenceNumber` ensures PO/Tab uniqueness across the workflow and is consulted/advanced before new contracts are created or finalization ensures the counter stays ahead.
- `ProcessContract.calculate_contract_value`, `calculate_plan_gross`, and `update_calculated_values` are relied upon when `update_contract_values` recomputes totals and inserts “STATZ” splits if totals drift.
- `ProcessContractSplit` exposes `create_split`, `update_split`, and `delete_split` classmethods used by both the form and AJAX endpoints.
- API helpers (`api_views`) support adding CLIN clones (copying CLIN `0001`), updating individual fields with conversions, deleting CLINs, saving entire CLIN payloads in `save_clin`, and recalculating splits/plan gross when values change.

## 11. Integrations and Cross-App Dependencies
- Imports from `contracts.models` (`Contract`, `Clin`, `Buyer`, `IdiqContract`, `ClinType`, `SpecialPaymentTerms`, `ContractType`, `SalesClass`, `PaymentHistory`, `ContractSplit`, `ContractStatus`) show that `processing` writes the final authoritative records back into the `contracts` app and references the same lookup tables.
- `products.models.Nsn` and `suppliers.models.Supplier` supply NSN and supplier FK targets for `ProcessClin`.
- `QueueContract`/`QueueClin` use `AuditModel` and `Company`, linking them to the shared company/metadata stored in `contracts`.
- Views like `match_buyer`/`match_nsn`/`match_supplier` query their respective models and expect IDs from modals generated with JS templates, so renaming those lookups requires coordination across the `processing/static` JS and `templates`.
- `ProcessContractSplit` data is mirrored into `contracts.ContractSplit` when finalizing, so renaming fields or table names affects both apps. Similarly, `PaymentHistory` entries created during finalization use the `ContentType` framework tied to `contracts`.

## 12. URL Surface / API Surface
- **Queue + batch:** `/processing/queue/`, `/processing/start-new-contract/`, `/processing/start-processing/<queue_id>/`, `/processing/get-next-numbers/`, `/processing/upload/`, `/processing/download-template/`, `/processing/download-test-data/`.
- **Processing contract UI:** `/processing/contract/<pk>/`, `/processing/contract/<pk>/edit/`, `/processing/contract/<id>/save/`, `/processing/contract/<id>/finalize/`, `/processing/contract/<id>/finalize-and-email/`, `/processing/process-contract/<id>/cancel/`, `/processing/process-contract/<id>/mark-ready/`.
- **Matching endpoints:** `/processing/match-buyer/<id>/`, `/processing/match-nsn/<id>/`, `/processing/match-supplier/<id>/`, `/processing/match-idiq/<id>/`.
- **AJAX/API:** `/processing/api/...` handles GET/PUT for processing contracts, create/update/delete CLINs, update single fields, `save_clin`, and `update_contract_values`.
- **Splits:** `/processing/contract/split/create/`, `/processing/contract/split/<split_id>/update/`, `/processing/contract/split/<split_id>/delete/`.
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
- `migrations/0001_initial.py` introduced the core tables; subsequent migrations tweak `ProcessContract.plan_gross`, `ProcessClin` references, `QueueContract.queue_id`, and rename `ContractSplit` to `ProcessContractSplit`.
- Migration `0012` adds `company` fields to `ProcessClin`/`ProcessContract`, suggesting a cleanup to track company ownership.
- Migration `0013` adjusted `nsn`/`supplier` FKs, showing this schema mutates when the supplier/NSN relationships need stricter validation.
- No migration touches appear after late 2025, implying schema is stable but still small enough that naming changes ripple into both the `processing` and `contracts` splits when finalizing.

## 17. Known Gaps / Ambiguities
- Entire app lacks tests (no coverage for matching logic, CSV ingestion, finalization, or form handling).
- JavaScript for splitting (`process_contract.js`, `*_modal.js`) drives the UI, but the server-side `ProcessContractForm.save` expects POST keys like `splits-<id>-<field>`—the template code that produces those keys is not easy to trace from this repo view without running the page.
- `matching_views` only searches `Buyer`, `Nsn`, `Supplier` by `__icontains`; there is no fallback for creating new records, yet the README states the UI should allow “create a new record,” so it’s unclear whether that path is handled elsewhere.
- The `save_contract` and `save_clin` endpoints log a lot of `print`/`logger.debug` statements, indicating debugging is still active; expect noise and potential secrets logged in console output during heavy usage.

## 18. Safe Modification Guidance for Future Developers / AI Agents
1. Keep queue/process syncing intact — renaming `QueueContract`/`QueueClin` fields requires updates to both `start_processing`, `upload_csv`, and the templates with matching form names.
2. When adjusting match logic, update both the modal templates (`processing/templates/processing/modals/*.html`), JS (`static/processing/js/*_modal.js`), and the POST-handling views (`match_*` in `processing_views.py` and `matching_views.py`).
3. Before renaming `ProcessContractSplit`, ensure finalization recreates matching `contracts.ContractSplit` rows and `update_contract_values` still sums the right decimals.
4. Any change to `confirm` finalization (e.g., adding validations) must keep `PaymentHistory` creation and queue/the sequence handling in sync so PO/Tab counters and completed contracts remain consistent.
5. Re-run `processing_views.upload_csv` logic and the dedup/validation loops when altering columns; the view relies on exact CSV headers and will break quietly if names change.

## 19. Quick Reference
- **Primary models:** `QueueContract`, `QueueClin`, `ProcessContract`, `ProcessClin`, `ProcessContractSplit`, `SequenceNumber`.
- **Main URLs:** `/processing/queue/`, `/processing/contract/<pk>/edit/`, `/processing/start-processing/<queue_id>/`, `/processing/contract/<id>/finalize/`, `/processing/upload/`, `/processing/api/processing/<id>/...`.
- **Key templates:** `processing/contract_queue.html`, `processing/process_contract_form.html`, `processing/process_contract_detail.html`, plus modals under `processing/modals/`.
- **Key dependencies:** `contracts` (Contract/Clin/Buyer/.../ContractSplit/PaymentHistory), `products.Nsn`, `suppliers.Supplier`, shared `Company` model.
- **Risky files:** `views/processing_views.py` (central workflow, finalization, CSV import), `forms.py` (split persistence), `static/processing/js/process_contract.js` (AJAX state machine), `processing/models.py` (schema/SequenceNumber), and the large templates that must stay aligned with API payloads.
