# AGENTS.md — `processing` App
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

> **Read `processing/CONTEXT.md` first.** This file adds editing-safety rules on top of it; it does not duplicate it.

---

## 1. Purpose of This File

Defines safe-edit guidance for the `processing` Django app. Every rule below is grounded in the actual code. Labels like *(inferred)* are used where a risk is not directly visible in source.

---

## 2. App Scope

**Owns:**
- Queue tables (`QueueContract`, `QueueClin`) — staging area for incoming contract data
- Processing tables (`ProcessContract`, `ProcessClin`, `ProcessClinSplit`) — editable workflow state
- Sequence counters (`SequenceNumber`) — PO/Tab number generation
- All HTTP endpoints for the queue dashboard, contract editing, matching, CSV import, finalization, and split management
- All JS assets that drive the AJAX save loop and match modals

**Does not own:**
- Canonical domain records: `Contract`, `Clin`, `ClinSplit`, `PaymentHistory` — these live in `contracts`
- NSN master data — lives in `products`
- Supplier master data — lives in `suppliers`
- Authentication/permissions infrastructure — provided by Django and the `users` app

**Role:** Central workflow/staging app. It is the most complex and most side-effect-heavy app in the project. Changes here can silently corrupt finalized contracts if made carelessly.

---

## 3. Read This Before Editing

### Before changing models
- Read `processing/models.py` in full — field names are referenced by string in templates, JS, and views
- Read `processing/migrations/` — 13 migrations exist; understand what has changed before adding constraints or renaming
- Grep for the field name across the entire repo before renaming anything
- Check `processing/views/processing_views.py` `finalize_and_email_contract` — it maps `ProcessContract`/`ProcessClin` fields directly to `Contract`/`Clin` fields by name

### Before changing views
- Read `processing/urls.py` — URL names are used in `reverse()` calls and in JS `fetch()` calls; both break on rename
- Read `processing/static/processing/js/process_contract.js` — it constructs API URLs using the URL names returned by the server
- Read `processing/views/api_views.py` and `processing/views/matching_views.py` together with `processing_views.py` — they form a single logical surface

### Before changing forms
- Read `ProcessContractForm.save()` and `persist_clin_splits_for_contract` — POST keys are `clin-<clin_id>-splits-<split_id|new n>-<field>`; the template/JS must match
- Read `ProcessClinForm.clean()` — it auto-calculates `item_value` and `quote_value`; removing these calculations breaks finalization validation
- Read the corresponding JS in `process_contract.js` and `clin_handling.js` — form field names must match what JS sends

### Before changing templates
- Read `process_contract_form.html` and the five modal templates under `processing/templates/processing/modals/`
- Check which JS functions reference modal element IDs or data attributes by name
- Confirm the POST key names that JS constructs match what forms and API views expect

### Before changing the finalization flow
- Read `finalize_and_email_contract` in full (it is ~200 lines)
- Read `finalize_contract` as well — it is a simpler variant but both paths share validation logic
- Any change to finalization must keep `PaymentHistory` creation, `ClinSplit` creation (per finalized CLIN from `ProcessClinSplit` rows), `SequenceNumber` advancement, and queue record deletion all in sync

### Before changing CSV import
- Read `upload_csv` — it validates exact column names; changing expected headers breaks silent import failures
- Required headers are hardcoded: `Contract Number`, `Buyer`, `Award Date`, `Due Date`, `Contract Value`, `Contract Type`, `Solicitation Type`, `Item Number`, `Item Type`, `NSN`, `NSN Description`, `Order Qty`, `UOM`, `Unit Price`

### Before changing award PDF intake
- Before changing award PDF intake: `_section_b_slice()` extracts text from SECTION B to the next SECTION X — do not add character limits or reintroduce `_RE_SECTION_B` (it was removed). The full Section B goes to `_extract_clins_via_claude_api()` which calls claude-sonnet-4-20250514. Two CLIN variants exist — see the prompt in `_extract_clins_via_claude_api` for format examples; both variants are documented with examples in the prompt itself. `_RE_DELIVER_BY` matches both DELIVER BY: and DELIVERY DATE: — do not split these back into separate patterns. Per-CLIN CAGE/PN: cage code is the manufacturer/supplier; Block 9 is always STATZ. S-codes are valid NSN values — do not null them, do not skip those CLINs, the description comes from the label preceding the CLIN row. Contract due date logic: ADO days (Block 10) + award date takes priority; fallback is latest CLIN due date. `uom` must be explicitly copied in `start_processing` `ProcessClin.objects.create()` — this was a bug fixed in this session; any new `QueueClin` fields added in future must follow the same pattern.

---

## 4. Local Architecture / Change Patterns

- **Business logic lives in `views/processing_views.py`**, not in a services layer. There is no `services.py`. All finalization, sequencing, and queue management is inline in view functions.
- **Validation is split across three places:** Django form `clean()` methods, API endpoint parsing in `api_views.py`, and the finalization pre-checks in `processing_views.py`. All three must stay consistent.
- **The JS layer does not trust the server state** — `process_contract.js` continuously fires AJAX saves. The server must handle idempotent partial saves gracefully. Do not add server-side side effects to the `save_contract`, `update_clin_field`, or `update_process_contract_field` endpoints without understanding the call frequency.
- **Protected fields exist by convention, not framework enforcement.** `update_clin_field` and `update_process_contract_field` reject writes to `nsn`, `supplier`, `buyer` and require the match endpoints instead. If you add new protected fields, update these guards explicitly.
- **Admin is intentionally read-only** for `QueueContract`. The only writable admin action is `force_delete_contracts`. Do not add `has_add_permission=True` or `has_change_permission=True` without understanding the cascade implications.
- **No background tasks or signals are in use.** Everything is synchronous HTTP. This means long CSV uploads block the request.

---

## 5. Files That Commonly Need to Change Together

### Model field rename
`models.py` → `migrations/` → `views/processing_views.py` (field mappings in finalize functions) → `views/api_views.py` (JSON serialization) → `forms.py` (field lists, `clean()`) → templates (form field names) → `static/processing/js/*.js` (field name strings in fetch payloads)

### New CLIN field
`models.py` → new migration → `forms.py` (`ProcessClinForm` fields + widgets) → `views/api_views.py` (`update_clin_field`, `save_clin`) → `views/processing_views.py` (`finalize_and_email_contract` mapping to `Clin`) → `templates/processing/process_contract_form.html` → `static/processing/js/clin_handling.js` or `process_contract.js`

### New match modal (e.g., add a new lookup type)
`views/matching_views.py` (search endpoint) → `urls.py` (new route) → `templates/processing/modals/<new>_modal.html` → `static/processing/js/<new>_modal.js` → `process_contract_form.html` (include modal + wire button)

### Split management change
`models.py` `ProcessClinSplit` → `forms.py` `persist_clin_splits_for_contract` / `ProcessContractForm.save` → `views/processing_views.py` (`create_split_view`, `update_split_view`, `delete_split_view`, `calc_splits_view`, `save_contract`) → `views/api_views.py` `update_contract_values` (no auto-STATZ) → `templates/processing/process_contract_form.html` → `static/processing/js/process_contract.js`

### Finalization change
`views/processing_views.py` `finalize_contract` + `finalize_and_email_contract` → `contracts/models.py` (target model fields) → test by completing a full queue-to-finalize flow manually

### New QueueClin field from PDF/CSV ingestion
`pdf_parser.py` or `upload_csv` → `QueueClin` model/migration → `start_processing` `ProcessClin.objects.create()` call — field must be explicitly copied or it is silently lost at queue-to-processing transition.

### New QueueContract field from PDF ingestion
`pdf_parser.py` (regex constants + `_extract_*` function + `AwardParseResult`
dataclass field + `ingest_parsed_award` `common_contract` dict) → `QueueContract`
model/migration → `start_processing` in `processing_views.py` (must explicitly
copy the field to `ProcessContract.objects.create(...)` or it is silently lost
at queue-to-processing transition) → `ProcessContract` model/migration if the
field does not already exist there.

---

## 6. Cross-App Dependency Warnings

### This app depends on:
| App | What is used |
|---|---|
| `contracts` | `Contract`, `Clin`, `ClinSplit`, `Buyer`, `IdiqContract`, `ContractType`, `SalesClass`, `ClinType`, `SpecialPaymentTerms`, `PaymentHistory`, `ContractStatus`, `AuditModel`, `Company` |
| `products` | `Nsn` — FK target for `ProcessClin.nsn` and `QueueClin.matched_nsn` |
| `suppliers` | `Supplier` — FK target for `ProcessClin.supplier` and `QueueClin.matched_supplier` |
| `users` / `auth` | `User` — FK for `processed_by`, `created_by`, `modified_by` |

### Other apps that depend on this app:
- No other app appears to import from `processing` directly *(inferred from repo structure — verify with `grep -r "from processing" .`)*
- `processing` is a terminal workflow app; output lands in `contracts`

### Finalization coupling:
`finalize_and_email_contract` writes to `contracts.Contract`, `contracts.Clin`, `contracts.ClinSplit` (from each `ProcessClinSplit` on the matching `ProcessClin`), and `contracts.PaymentHistory`. Any schema change in those models must be reflected in the finalization mapping in `processing_views.py`.

### Sequence numbers:
`SequenceNumber` is local to `processing` but the PO/Tab numbers it generates are stored permanently in `contracts.Contract` and `contracts.Clin`. Resetting or corrupting `SequenceNumber` will cause duplicate PO/Tab assignments.

---

## 7. Security / Permissions Rules

- Every view function in `processing_views.py`, `api_views.py`, and `matching_views.py` is decorated with `@login_required`. **Do not remove this decorator from any endpoint.**
- `delete_queue_contract` enforces `request.user.is_superuser` — preserve this check when modifying the delete path.
- `download_test_data` raises `PermissionDenied` if `settings.DEBUG` is `False` — do not weaken this guard.
- `start_processing` and `initiate_processing` use `select_for_update` inside an atomic transaction to prevent two users from claiming the same queue item. Do not refactor these into non-atomic paths.
- The `nsn`, `supplier`, and `buyer` fields on process records are protected from direct writes in `update_clin_field` and `update_process_contract_field`. This is a deliberate data integrity control, not a bug. Preserve these guards.
- Finalization validates buyer, NSN, and supplier presence before creating canonical records. Do not add bypass paths.

---

## 8. Model and Schema Change Rules

- **Before renaming any field**, run `grep -r "<field_name>" processing/ contracts/ products/ suppliers/ templates/ static/` — field names appear in JS fetch payloads, template variable lookups, and view-level mappings.
- **`ProcessContract.status` choices** (`draft`, `in_progress`, `ready_for_review`, `completed`, `cancelled`) are referenced by string in views and templates. Changing choice values requires updating all string comparisons.
- **`SequenceNumber`** has only one row. Do not add unique constraints or change the auto-increment behavior without understanding that `get_po_number()` / `get_tab_number()` are called inside finalization transactions. Schema changes here can cause deadlocks.
- Staging `ProcessClinSplit` (processing) vs `contracts.ClinSplit` (finalized) — different tables. Migration history still mentions older `ProcessContractSplit`; `0019` moved splits onto `ProcessClin`.
- When adding a new FK to `ProcessClin` or `ProcessContract`, decide whether it should be nullable (staging data is often incomplete) and whether it must be mapped to the canonical model during finalization.
- `QueueContract` and `QueueClin` use `AuditModel` from `contracts`. If `AuditModel` changes, these models are affected.

---

## 9. View / URL / Template Change Rules

- **URL names are used in JS.** The server renders URL patterns into template `<script>` blocks or `data-*` attributes that JS reads. Renaming a URL name in `urls.py` requires finding all JS references to that URL string.
- **`app_name = 'processing'`** is set in `urls.py`. All `reverse()` calls use `'processing:<name>'`. Search for these before renaming routes.
- **`process_contract_form.html`** is large and loads all five modal templates via `{% include %}`. When editing the main form template, verify modal `id` attributes that JS references by name have not drifted.
- **`ProcessContractUpdateView`** injects `ProcessClinFormSet` into context — the template iterates it. If you add or remove formset fields, update the template CLIN table and the JS that reads those fields.
- **`save_contract`** at `/processing/save_contract/` is a duplicate alias for `/processing/contract/<id>/save/`. Both exist in `urls.py`. If you deprecate one, check JS for which URL it uses.

---

## 10. Forms / Serializers / Input Validation Rules

- **`ProcessContractForm.save()`** and **`persist_clin_splits_for_contract`** parse `clin-*-splits-*` keys. If the JS changes the key format, splits will not persist.
- **`ProcessClinForm.clean()`** auto-calculates `item_value = order_qty * unit_price` and `quote_value = order_qty * price_per_unit / price_per_unit_divisor`. Do not remove or restructure this without updating the API endpoints that also perform these calculations (`update_clin_field`, `save_clin`).
- **Decimal parsing in `upload_csv`** strips `$` and `,` before converting. If you add new decimal fields to the CSV, follow the same stripping pattern.
- **Date parsing in `upload_csv`** expects `YYYY-MM-DD` format. The CSV template and test data must match this format — update `download_csv_template` if column names or date format assumptions change.
- There are no DRF serializers. All API endpoints use manual JSON parsing and Django form validation.

---

## 11. Background Tasks / Signals / Automation Rules

- **No Celery tasks, signals, or cron jobs exist in this app.** All processing is synchronous.
- `upload_csv` runs inside `transaction.atomic()` — a large CSV upload holds a transaction open for its entire parse duration. This is a known performance trade-off, not a bug.
- There are no `post_save` or `pre_delete` signals on any model in this app.
- No management commands exist in this app.

---

## 12. Testing and Verification Expectations

- **`processing/tests.py` is empty.** There is zero automated test coverage for this app.
- After any change, verify manually:
  1. Upload a CSV via `/processing/upload/` — confirm rows appear in the queue
  2. Start processing a queue item — confirm `ProcessContract` and `ProcessClins` are created
  3. Match buyer, NSN, and supplier via modals
  4. Adjust CLINs and verify `contract_value` / `plan_gross` recalculate
  5. Finalize via `/processing/contract/<id>/finalize-and-email/` — confirm `Contract` and `Clin` records appear in the `contracts` app
  6. Confirm `QueueContract` and `ProcessContract` are deleted after finalization
  7. Confirm `SequenceNumber` advanced correctly
- After form changes: test the `clin-<id>-splits-new-<n>-<field>` POST flow by adding a new split row in a CLIN block
- After URL changes: confirm JS fetch calls still resolve (check browser network tab)
- After model changes: run `python manage.py makemigrations --check` to confirm no missing migrations

---

## 13. Known Footguns

1. **Finalization deletes staging records.** `finalize_and_email_contract` deletes `ProcessContract` and `QueueContract` atomically. If the `Contract` creation fails mid-transaction, everything rolls back — but if you add code after the delete and before the commit, you risk data loss.

2. **JS constructs URLs from server-rendered values.** If a template stops rendering a URL into its expected JS variable, fetch calls fail silently with 404s that look like save errors in the UI.

3. **`SequenceNumber` has one row.** Code calls `SequenceNumber.objects.first()` without a guard in some paths. If the table is empty (e.g., fresh database), this returns `None` and crashes at attribute access. Do not delete the single `SequenceNumber` row.

4. **`ProcessClinSplit` vs `contracts.ClinSplit`** — both exist. `processing` creates `ProcessClinSplit` rows per CLIN during editing. `finalize_and_email_contract` creates `contracts.ClinSplit` rows from them. They are separate tables. Confusion between them causes finalization to silently skip split creation.

5. **Protected fields are enforced only in two API endpoints.** If you add a new endpoint that writes to `ProcessClin.nsn` or `ProcessClin.supplier` directly, you bypass the match workflow and leave `nsn_text`/`supplier_text` out of sync.

6. **The auto-STATZ split creation in `update_contract_values` has been removed.** STATZ splits are created explicitly via the per-CLIN **Calc Splits** button, which calls `calc_splits_view`. Do not re-add auto-creation logic to `update_contract_values`.

7. **`print` / `logger.debug` statements are active in `processing_views.py` and `api_views.py`.** These log partial contract data to console. In production this is noise; do not add more print statements and consider removing existing ones when touching those functions.

8. **`services/pdf_parser.py` — `_CLIN_VARIANT2_LINE`:** The pattern must stay anchored at line start (`(?:^|\n)\s*`) so mid-line `NSN/MATERIAL:` on the same pdfplumber string cannot produce a false variant-2 match with a bogus UOM. **`QueueClin.ia` / `QueueClin.fob`** stored values are exactly `'O'` and `'D'` (see `processing/models.py`); `_point_word_to_choice` must stay aligned with those tuples if choices ever change.

9. **CSV deduplication is by `contract_number` only.** It checks `Contract.objects.filter(contract_number=...)` and `QueueContract.objects.filter(contract_number=...)`. A re-upload with the same contract number but different CLINs will be silently dropped. Changing this logic requires updating `upload_csv` dedup checks and the error messages returned to the user.

10. **`cancel_process_contract` accepts both `process_contract_id` and `queue_id` as optional kwargs.** Two URL patterns call this same function. Both code paths must remain valid if the function signature changes.

11. **`startProcessing()` and `resumeProcessing()` in `contract_queue.html`** use `data.redirect_url` from the JSON response when the server supplies it (IDIQ resume/start paths). Hardcoding the fallback `process_contract_edit` URL in the template is intentional for non-IDIQ contracts.

12. **`match_nsn` and `match_supplier` are dual-purpose.** Same URL accepts **GET** with `action=search` and `q` (min length 3 on the client) for JSON `results`, and **POST** JSON for either `{id}` / `{supplier_id}` match-by-ID or `{action: 'create', ...}` to create and link. The standard contract form modals continue to use **POST** with `{ id: … }` (NSN) or `{ supplier_id: … }` (supplier) for matching; only the IDIQ inline page relies on GET search and POST create on these endpoints.

13. **`_normalize_nsn` in `pdf_parser.py` is a thin wrapper around `contract_utils.normalize_nsn`.** Do not add NSN normalization logic to `pdf_parser.py` directly — update `contract_utils.py` instead. **`detect_contract_type`** reads position 9 (the character between the 2nd and 3rd hyphens in a dashed DLA number). The `_RE_IDIQ_TEXT_DETECT` regex phrase detection in `parse_award_pdf` is a **fallback only** — position-9 detection takes priority when the contract number yields a mapped type. **`_apply_contract_number_rules`** in `pdf_parser.py` still returns `"Delivery Order"` / `"Purchase Order"` strings as initial values that get overridden by `detect_contract_type`. Do not remove `_apply_contract_number_rules` — it also handles the delivery-order/base-contract swap logic.

14. **`solicitation_type` is regex-extracted with `SDVOSB` as the default.** `_extract_solicitation_type` in `pdf_parser.py` uses FAR-clause references (52.219-27/-29/-30/-3/-4/-18/-6) as the primary path and narrative phrases as fallback; when neither matches, the value defaults to `SDVOSB` and a parse note is appended. There is no Claude API fallback for this field. The parser previously hardcoded `STATZ` (a sales-class value) into `solicitation_type` at five sites — fixed in the same change that introduced extraction. Do not reintroduce `STATZ` as a solicitation_type value.

15. **`option_length` on `IdiqContract`:** Stores total option period length in months (integer). `0` is valid (Zero Options). In views, templates, and JS, use explicit checks (`is not None`, `!== ''` for form fields), not truthiness, so `0` is not dropped.

---

## 14. Safe Change Workflow

1. Read `processing/CONTEXT.md` for domain context
2. Read the specific files involved in your change (models, views, forms, templates, JS)
3. Run repo-wide grep for any field name, URL name, or function name you plan to change
4. Make the minimum change needed — this app has no tests, so partial changes are hard to catch
5. Update all coupled files (see Section 5) before considering the change complete
6. Manually walk through the affected user flow end-to-end (queue → edit → finalize)
7. Run `python manage.py makemigrations --check` if models changed
8. Check browser network tab for any 404 or 500 errors during the manual flow
9. Summarize which canonical `contracts` records were verified to be correct after finalization

---

## 15. Quick Reference

| Category | Files |
|---|---|
| Primary models | `processing/models.py` — `QueueContract`, `QueueClin`, `ProcessContract`, `ProcessClin`, `ProcessClinSplit`, `SequenceNumber` |
| Core workflow | `processing/views/processing_views.py` — `start_processing`, `finalize_contract`, `finalize_and_email_contract`, `upload_csv`, `upload_award_pdf`, `save_to_sharepoint` (stub) |
| API layer | `processing/views/api_views.py`, `processing/views/matching_views.py` |
| Form logic | `processing/forms.py` — `ProcessContractForm.save()`, `ProcessClinForm.clean()` |
| UI state machine | `processing/static/processing/js/process_contract.js` |
| Match modals | `processing/static/processing/js/*_modal.js` + `processing/templates/processing/modals/` |
| Coupled cross-app writes | `contracts.Contract`, `contracts.Clin`, `contracts.ClinSplit`, `contracts.PaymentHistory` |
| Sequence integrity | `SequenceNumber` — one row, do not delete |
| Riskiest edits | Finalization flow, field renames, URL renames, split key format in forms/JS |
| Security-sensitive | `@login_required` on all views, `is_superuser` on delete, `DEBUG` guard on test data download |
| Test coverage | **None** — all verification must be manual |

---

## 16. UI Improvements

(`processing/templates/processing/process_contract_form.html` and related layout)

- Sidebar buttons standardized for centering (removed `.row`).
- Vertical density optimized in CLIN detail blocks.
- Persistent expansion state implemented via `localStorage`.
- CLIN save auto-chain: after a successful CLIN save, the page auto-clicks that CLIN's **Calc Splits** button and then calls `updateContractValues()` after an 800ms delay. Both controls remain visible as manual overrides.
- Supplier Due Date is intentionally optional. Leave it blank during ingestion and early processing; Contract Admins fill it later when POs are issued. Never treat this field as required.


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
