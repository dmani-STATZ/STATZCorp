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
| `created_at`, `modified_at` | Audit timestamps |

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

## Editor (Phase 2a)
The editor (`intake/templates/intake/draft_edit.html`) is a flat HTML form
whose field names follow a strict prefix convention; `intake/forms_parse.py`
reshapes the POST back into the per-type JSON schema:

| Prefix             | Maps to                        |
|--------------------|--------------------------------|
| `f_<scalar>`       | top-level scalar               |
| `clin-<i>-<field>` | `clins[i]`                     |
| `fin-<i>-<field>`  | `finance_lines[i]`             |
| `pkg-<field>`      | `packaging` (singleton)        |
| `nsn-<i>-<field>`  | `approved_nsns[i]` (IDIQ)      |
| `supp-<i>-<field>` | `approved_suppliers[i]` (IDIQ) |

Unknown keys are dropped at parse time. All-blank rows are dropped. Date /
Decimal coercion is deferred to the Pydantic schema on `DraftContract.save()`.

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

Supported types: **AWD, PO, DO, IDIQ, INTERNAL, MOD, AMD**.

| Type     | Requirements                                       | Canonical effect                                   |
|----------|----------------------------------------------------|----------------------------------------------------|
| AWD/PO   | `buyer_id` + ≥1 CLIN, each with `nsn_id`+`supplier_id` | new Contract + Clins + optional Packaging + finance_lines on first CLIN |
| DO       | Same as AWD/PO + `parent_idiq_id`                  | new Contract with `idiq_contract` FK set           |
| IDIQ     | (nothing required; buyer optional)                 | new IdiqContract + cross-product IdiqContractDetails |
| INTERNAL | If any CLIN provided, each must be fully matched   | new Contract; CLINs optional; notes append as Note |
| MOD/AMD  | `parent_contract_id` matched                       | appends a tagged Note on the parent Contract; returns parent (no new row) |

`finance_lines` (root-level on the intake JSON) attach to the FIRST canonical
CLIN. `ContractFinanceLine` is keyed to Clin, not Contract, so this is a
pragmatic placement; analysts can re-bucket via the Finance Audit page.

URL: `intake:finalize_draft` → `POST /intake/drafts/<pk>/finalize/`
(requires lock + status=`ready_for_review`). On success for AWD/PO/DO/INTERNAL,
redirects to `/processing/email-compose/` with subject + body pre-populated
(matches the long-standing processing-app email workflow). MOD/AMD skip the
email step.

## PDF Ingestion (Phase 3c)
`intake/ingest.py` wraps `processing.services.pdf_parser.parse_award_pdf`
(the existing DLA 1155 parser) and converts the resulting
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
  `intake:upload_pdfs` endpoint, reuses `processing.services.pdf_parser`)
- **Finalization for all seven types** (AWD/PO/DO/IDIQ/INTERNAL/MOD/AMD)
- **`ContractFinanceLine` shred** — attaches root-level finance_lines to the
  first canonical CLIN
- **DIBBS ingestion** — `python manage.py intake_dibbs_pull --date YYYY-MM-DD`
  creates skeleton drafts (status=queued, pdf_parse_status=no_pdf) from the
  DIBBS Awards table. Reuses `sales.services.dibbs_awards_scraper` as-is.
- **Finalization email** — redirects to `/processing/email-compose/` with
  prefilled subject + body on Contract-creating finalize paths

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
- Templates extend `contracts/contract_base.html`.
- No signal coupling. No `transactions` audit hooks on `DraftContract` —
  drafts are pre-canonical and out of scope for audit history.
