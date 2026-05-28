# intake — App Context

## Purpose
Entry point for new contracts. Captures inbound work, holds it in a draft state
while analysts review and augment it, and finalizes it into the live `contracts`
app once complete.

**Drafts are not contracts.** A draft is a workspace. It exists to be finalized.
Drafts are not reported on, not queried for BI, and not a system of record.

## Visual Language
Templates intentionally mirror `processing/` so analysts learning the new system
see familiar UI. The backend, however, is JSON-backed with Pydantic validation
rather than the wide-column staging tables `processing` uses.

## Data Model

### `DraftContract`
A single model holds every contract type. Type-specific fields and child
records live in the `data` JSONField, validated per `contract_type` by a
Pydantic schema in `intake/schemas.py`.

First-class columns:

| Column | Purpose |
|---|---|
| `contract_number` | Unique identity; rejects re-injection at the DB layer |
| `contract_type` | `AWD`, `PO`, `DO`, `IDIQ`, `MOD`, `AMD`, `INTERNAL` |
| `status` | `queued`, `in_progress`, `ready_for_review`, `completed`, `cancelled` |
| `locked_by`, `locked_at` | 30-minute soft edit lock (see `intake/locks.py`) |
| `pdf_parse_status` | `pending`, `no_pdf`, `parseable`, `partial`, `success` |
| `data` | JSONField — everything else |
| `final_contract` | Set briefly at finalization; draft is then deleted |
| `company` | FK to `contracts.Company`; set at ingestion (DIBBS CAGE lookup or PDF upload active company) |
| `sharepoint_folder_status` | `pending`, `exists`, `not_found`, `created`, `error` — folder probe/create state |
| `created_at`, `modified_at` | Audit timestamps |

SharePoint folder path is stored in `data['sharepoint_folder_path']` (not a model column).

### `data` JSON shape
Varies by `contract_type`. See `intake/schemas.py` for the authoritative
per-type schema. Matched FK lifecycle: both `*_text` (parsed) and `*_id`
(matched) keys live in JSON during intake. On finalization, `*_id` values
become real FKs on the canonical `contracts.*` tables and the draft is deleted.

**Dates are always `date`, never `datetime`** — both in columns and in JSON.

### Schema validation
`DraftContract.save()` calls `schemas.validate_data(contract_type, data)` on
every write. Invalid payloads raise `DraftDataValidationError` and the save
is rejected. Without enforced schema discipline, the JSON-first architecture
rots — parsers and templates drift on key names and old records become
incompatible with new code. Validation is a hard requirement.

## Lock Model
- Acquired by `intake.locks.acquire(draft, user)` inside a `select_for_update`
  transaction.
- 30-minute expiry (`LOCK_DURATION`). Expired locks may be claimed by any user.
- View save endpoints MUST call `intake.locks.assert_holds(draft, user)` before
  applying edits. This rejects the "lock expired → reclaimed by user B → user A
  saves" overwrite scenario.
- Bulk clear: `python manage.py clear_stale_locks` (admin also has a per-row
  and bulk action).

## URLs
- `intake:queue` — `GET /intake/` — draft worklist
- `intake:start_draft` — `POST /intake/drafts/<pk>/start/` — acquire lock,
  redirect to editor
- `intake:release_draft` — `POST /intake/drafts/<pk>/release/`
- `intake:delete_draft` — `POST /intake/drafts/<pk>/delete/`
- `intake:edit_draft` — `GET /intake/drafts/<pk>/edit/` — JSON-backed editor
  (requires user to hold the lock)
- `intake:save_draft` — `POST /intake/drafts/<pk>/save/` — write JSON under lock
- `intake:mark_ready` — `POST /intake/drafts/<pk>/mark-ready/` — save +
  transition to `ready_for_review` + release lock
- `intake:cancel_draft` — `POST /intake/drafts/<pk>/cancel/` — transition to
  `cancelled` + release lock

## Editor
The editor (`intake/templates/intake/draft_edit.html`) is a CLIN-card
form whose field names follow a strict prefix convention;
`intake/forms_parse.py` reshapes the POST back into the per-type JSON
schema:

| Prefix                              | Maps to                         |
|-------------------------------------|---------------------------------|
| `f_<scalar>`                        | top-level scalar (incl. `f_sales_class_id`) |
| `clin-<i>-<field>`                  | `clins[i]`                      |
| `clin-<i>-fin-<j>-<field>`          | `clins[i].finance_lines[j]`     |
| `clin-<i>-split-<j>-<field>`        | `clins[i].splits[j]`            |
| `pkg-<field>`                       | `packaging` (singleton)         |
| `nsn-<i>-<field>`                   | `approved_nsns[i]` (IDIQ)       |
| `supp-<i>-<field>`                  | `approved_suppliers[i]` (IDIQ)  |

Unknown keys are dropped at parse time. All-blank rows are dropped. Date /
Decimal coercion is deferred to the Pydantic schema on `DraftContract.save()`.

Contract-level scalars in `_CommonContractFields` include `award_date`,
`due_date` (contract-level `due_date` is derived at ingest as the earliest
CLIN `due_date`; analysts can override in the editor), `buyer_text` /
`buyer_id`, `sales_class_id` (defaults to the 'STATZ' SalesClass PK at
ingest if that record exists; analyst can change in editor),
`canonical_contract_type_id` (FK PK to `contracts.ContractType`; the
Bilateral/Delivery Order/etc. value written on the canonical Contract at
finalization — analyst-selected, optional), `plan_gross` (optional decimal;
planned gross value), `planned_split` (optional string; planned split
assignment). Both fields are auto-populated live in the editor: `plan_gross` is
set to Net Contract GP (sum of CLIN GPs minus packaging quote) and
`planned_split` is derived from all CLIN split rows as a plain
summed percentage total (e.g. "100"). Both remain user-editable. `nist` (optional bool; NIST flag on Contract), `contractor_name`,
`contractor_cage`, and related fields. `contractor_name` and
`contractor_cage` are parser provenance only — they round-trip in JSON but
are not shown in the editor UI.

INTAKE TYPE (`draft.contract_type`) is display-only in the editor. It is
set by the parser and drives schema routing. CONTRACT TYPE
(`data.canonical_contract_type_id`) is the analyst-selected FK to
`contracts.ContractType` and is written to `Contract.contract_type` at
finalization.

CLIN data shape (per-CLIN JSON keys, see `DraftClin` in `schemas.py`):

- Contract data: `item_number`, `item_type` (P/G/C/L/M/Q/D; defaults to
  `P` when not parsed), `nsn_text` + `nsn_id` + `nsn_description`,
  `order_qty`, `uom`, `item_value` (government contract unit price from
  the 1155 parser via `ingest._clin_to_dict`), `due_date`, `ia` (O/D;
  mapped from `ClinParseResult.inspection_point` at ingest — previously
  missing from `_clin_to_dict`; value is `'O'` or `'D'`),
  `fob` (O/D)
- Supplier data: `supplier_text` + `supplier_id`, `supplier_due_date`,
  `special_payment_terms` (stringified PK), `unit_price` (supplier quote
  price — manual entry only, never populated from PDF ingest).
  `supplier_text` is pre-populated at ingest from the "PLACE OF INSPECTION
  FOR SUPPLIES" block using a two-level drill-down (contract-level default,
  CLIN-level override). Analyst can override via Match button.
- Nested children: `finance_lines: [{line_type, amount, notes}]`,
  `splits: [{company_name, percentage}]`

Packaging: hidden in the editor until the analyst clicks **+ Add Packaging**,
or auto-shown on load when any of `packhouse_supplier_text`,
`packhouse_supplier_id`, `quote_amount`, or `notes` is pre-filled. The
section sits above the CLIN stack. **Remove Packaging** clears all `pkg-*`
inputs so the next save drops the packaging block from JSON.

PO Number is display-only in the editor (`Assigned when submitted`). It is
assigned post-finalization by the processing app — not a draft field.

GP calculation per CLIN:
`contract_total = item_value × order_qty`
`quote_total = unit_price × order_qty`
`planned_gp = contract_total − (quote_total + Σ finance_lines.amount)`

Note: `item_value` is the government contract UNIT price (from the 1155
parser). It must be multiplied by `order_qty` to get the contract total
before computing GP.

Split rows derive `split_value = planned_gp × percentage / 100` at
finalization (the editor shows it live; the value is not POSTed).

## Matcher (Phase 2b)
A single endpoint `intake:match` (`POST /intake/drafts/<pk>/match/`) handles
all four entity types (buyer / IDIQ / NSN / supplier) and every match site
in the JSON via a `target_path` grammar. Replaces the processing app's five
per-entity modals with one reusable modal partial + JS module.

Actions:
- `search` — read-only, no lock required.
- `apply` — locks the row, writes `*_text` + `*_id` (+ `*_description` /
  `*_cage` where relevant) under the chosen path, saves through schema
  validation.
- `clear` — strips `*_id` only (leaves `*_text` for the user to edit).
- `create` (Phase 2c) — inline-creates a canonical Buyer / NSN / Supplier
  from a minimal payload (`description`, `nsn_code`+`description`, or
  `name`+`cage_code`) and immediately applies it under the same atomic
  block. Dedup is enforced. IDIQ / Contract creation is intentionally
  not supported — use the contracts app forms.
- `creatable_types` — read-only convenience that returns the list of
  match_types supporting inline create.

The match modal pre-fills the inline-create panel's first field from the
parsed original text (`data-match-original` on the opener button). For NSN
matches, if the opener button carries a `data-match-original-description`
attribute (set by `_clin_card.html` from `nsn_description`), the description
field in the create panel is also pre-filled. For NSN matches, the "Parsed
value:" box also displays the stored `nsn_description` as a subtitle line
beneath the NSN code when one is present.

Target paths:
- `buyer`, `parent_idiq`, `parent_contract`, `packaging` (top-level)
- `clin:<i>:nsn`, `clin:<i>:supplier`
- `approved_nsn:<i>`, `approved_supplier:<i>`

Editor UX: matchers POST and save server-side as canonical state, so the
client reloads on `intake:match-applied`. The dirty-form guard in
`draft_edit.html` warns before clobbering unsaved manual edits.

## Finalization (Phase 3)
`intake/finalize.py` shreds a Ready-for-Review draft into canonical
`contracts.*` tables and deletes the draft on success. The whole flow runs
inside `transaction.atomic()` so any failure rolls back cleanly.

For AWD/PO/DO/INTERNAL contract creation, among other fields:
`data.canonical_contract_type_id` → `Contract.contract_type` (FK);
`data.plan_gross` → `Contract.plan_gross`; `data.planned_split` →
`Contract.planned_split`; `data.nist` → `Contract.nist`.

Supported types: **AWD, PO, DO, IDIQ, INTERNAL, MOD, AMD**.

| Type     | Requirements                                       | Canonical effect                                   |
|----------|----------------------------------------------------|----------------------------------------------------|
| AWD/PO   | `buyer_id` + ≥1 CLIN, each with `nsn_id`+`supplier_id` | new Contract + Clins + optional Packaging + finance_lines on first CLIN |
| DO       | Same as AWD/PO + `parent_idiq_id`                  | new Contract with `idiq_contract` FK set           |
| IDIQ     | (nothing required; buyer optional)                 | new IdiqContract + cross-product IdiqContractDetails |
| INTERNAL | If any CLIN provided, each must be fully matched   | new Contract; CLINs optional; notes append as Note |
| MOD/AMD  | `parent_contract_id` matched                       | appends a tagged Note on the parent Contract; returns parent (no new row) |

Per-CLIN `finance_lines` and `splits` are created inline on the matching
canonical `Clin`. Legacy root-level `finance_lines` are still accepted for
in-flight drafts and attach to the first canonical CLIN with a warning
(removed once the queue is clear of pre-redesign drafts).

URL: `intake:finalize_draft` → `POST /intake/drafts/<pk>/finalize/`
(requires lock + status=`ready_for_review`). On success for AWD/PO/DO/INTERNAL,
redirects to `/processing/email-compose/` with subject + body pre-populated
(matches the long-standing processing-app email workflow). MOD/AMD skip the
email step.

## PDF Ingestion (Phase 3c)
`intake/ingest.py` wraps `intake/pdf_parser.py` (the intake-owned DLA 1155
parser — no dependency on processing) and converts the resulting
`AwardParseResult` dataclass into the intake `data` JSON shape. The mapping
lives ONLY in `_result_to_data` — when the parser grows new fields, update
the mapping there.

`ingest_pdf(file, original_filename='...')` returns the new `DraftContract`
or raises:
- `IngestionError` — parser couldn't extract a contract_number / type, or
  schema validation rejected the converted data.
- `DuplicateContractNumber` — already exists as a draft or as a canonical
  `Contract`. We don't overwrite either side.

URL: `intake:upload_pdfs` → `POST /intake/upload/` (multipart, field name
`pdfs`, multi-file). Each file is processed independently; one bad PDF
does not abort the batch. Response is `{"results": [...]}` with per-file
outcomes.

UI: drag-and-drop zone on the queue page (`draft_queue.html`) that hits
the upload endpoint and reloads the queue on any success.

## What's Built (Phase 1 + 2a + 2b + 3a + 3c PDF)
- `DraftContract` model + migrations
- Pydantic schemas for all seven contract types
- Lock model + helpers + clear-stale management command
- Queue page (cloned visual language from `processing/contract_queue.html`)
- Admin with stale-lock filter, summary column, and bulk-clear action
- **JSON-backed editor** with Save / Mark Ready / Cancel flows, all asserting
  the soft lock before write
- POST → JSON parser (`forms_parse.parse_post`) with row dedup and unknown-key
  drop
- **Unified matcher** (`intake/matchers.py` + `intake:match` endpoint +
  `_match_modal.html` + `match_modal.js`) for buyer / IDIQ / NSN / supplier
- **Finalization** for AWD / PO / IDIQ (`intake/finalize.py` +
  `intake:finalize_draft` endpoint + Finalize button on the editor)
- **PDF ingestion** via drag-and-drop on the queue (`intake/ingest.py` +
  `intake/pdf_parser.py` + `intake:upload_pdfs` endpoint)
- **Finalization for all seven types** (AWD/PO/DO/IDIQ/INTERNAL/MOD/AMD)
- **`ContractFinanceLine` shred** — attaches root-level finance_lines to the
  first canonical CLIN
- **DIBBS ingestion** — `intake/services/queue_we_won_drafts.py` is called
  automatically as a piggyback inside `scrape_awards` (the daily WebJob)
  immediately after Processing queue injection. Creates skeleton DraftContracts
  (status=queued, pdf_parse_status=no_pdf) for the same STATZ-won awards
  injected into the Processing queue. No manual command needed.
- **Finalization email** — redirects to `/processing/email-compose/` with
  prefilled subject + body on Contract-creating finalize paths

**Company scoping** — `DraftContract.company` FK added. Queue view filters to all
companies the user has membership in (superusers see all, including unscoped
drafts with `company=None`). DIBBS injection resolves company via
`dibbs_company_cage` CAGE lookup (`sales.CompanyCAGE`).

**SharePoint folder status** — `DraftContract.sharepoint_folder_status` column
(`pending` / `exists` / `not_found` / `created` / `error`). Path stored in
`data['sharepoint_folder_path']`. Probe runs after DIBBS injection when company
is known; folder creation is reserved for PDF upload (next phase UI).

SharePoint scan API — POST /intake/api/scan-sharepoint/ (`intake:scan_sharepoint_drafts`). Accepts `draft_id` or `all=true`. Probes SharePoint and updates `sharepoint_folder_status` + `data['sharepoint_folder_path']` on each draft. Company-scoped: non-superusers only see their companies' drafts.

Queue SP column — Draft queue table shows SP folder status badge per row with per-row rescan icon and bulk "Scan SP" toolbar button.

Company column — Draft queue table shows company badge per row.

PDF upload creates folder — `upload_pdfs` calls `create_draft_sharepoint_folder` after successful ingestion. Non-blocking.

Draft documents browser — `contracts:intake_draft_documents_browser` at `/contracts/documents/draft/?draft_id=N`. Opens the shared documents browser popup in draft mode. Save Path writes to `draft.data['sharepoint_folder_path']` via `contracts:set_draft_file_path_api`. "Docs" button appears on each queue row. At finalization, `sharepoint_folder_path` is carried through to `Contract.files_url` (or `IdiqContract.files_url`) automatically.

## Not Yet Built (explicitly out of scope)
- CSV ingestion path — depends on an external group that has not delivered
  the CSV feed; deferred indefinitely
- "Add new" inline creation from the matcher modal
- Fetching the actual award PDF for a DIBBS-scraped row (the DIBBS site
  doesn't expose a direct award-PDF URL in the scraped table; analysts
  drop the PDF on the queue manually after the skeleton lands)
- "Add new" inline creation from the matcher modal (parity with processing's
  "Add as new Buyer/NSN/Supplier" buttons)

## Coupling
- Reads `contracts.models.Contract` for the "Already in DB" queue badge and
  for the `final_contract` FK target.
- Reads `sales.CompanyCAGE` (`dibbs_company_cage`) for company resolution at
  DIBBS injection time.
- Calls `contracts.services.sharepoint_service` and
  `contracts.services.sharepoint_paths` for SharePoint operations via
  `intake/services/sharepoint_intake.py`. Does **not** import from
  `processing.*`.
- Templates extend `contracts/contract_base.html`.
- No signal coupling. No `transactions` audit hooks on `DraftContract` —
  drafts are pre-canonical and out of scope for audit history.
