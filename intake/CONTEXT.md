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

## What's Built (Phase 1 + 2a)
- `DraftContract` model + migrations
- Pydantic schemas for all seven contract types
- Lock model + helpers + clear-stale management command
- Queue page (cloned visual language from `processing/contract_queue.html`)
- Admin with stale-lock filter, summary column, and bulk-clear action
- **JSON-backed editor** with Save / Mark Ready / Cancel flows, all asserting
  the soft lock before write
- POST → JSON parser (`forms_parse.parse_post`) with row dedup and unknown-key
  drop

## Not Yet Built
- **Phase 2b**: modal matchers (buyer / IDIQ / NSN / supplier) writing
  `*_text` + `*_id` pairs back to JSON. The editor currently exposes raw
  numeric ID inputs as placeholders.
- Finalization → `contracts.*` shred (Phase 3)
- PDF parser port from `processing/services/pdf_parser.py` (Phase 3)
- CSV + DIBBS ingestion paths (Phase 3)
- Finalization email (Phase 3)

## Coupling
- Reads `contracts.models.Contract` for the "Already in DB" queue badge and
  for the `final_contract` FK target.
- Templates extend `contracts/contract_base.html`.
- No signal coupling. No `transactions` audit hooks on `DraftContract` —
  drafts are pre-canonical and out of scope for audit history.
