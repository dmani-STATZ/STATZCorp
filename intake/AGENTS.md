# intake — AGENTS.md

Read `CONTEXT.md` first for app purpose, model shape, and lock semantics.

## Safe-Edit Rules

### Schema changes
- **Never bypass `intake.schemas.validate_data` for stored JSON.** If a new
  field is needed, add it to the per-type Pydantic schema first, then write
  it. Untyped writes will silently round-trip the wrong shape and break the
  next reader.
- When adding a key to a schema: prefer `Optional` defaults so existing
  drafts remain valid. A breaking schema change requires a data migration
  that re-validates and rewrites every existing `DraftContract.data`.
- Schema field naming convention: parsed text uses `*_text`, matched FK uses
  `*_id`. Both live side-by-side until finalization.

### Lock changes
- Any new save endpoint MUST call `intake.locks.assert_holds(draft, user)`
  before applying edits. Skipping this re-introduces the silent-overwrite
  bug the lock model exists to prevent.
- Don't tighten `LOCK_DURATION` without checking template/UX expectations —
  the 30-minute window is referenced in admin and queue UI copy.

### Finalization (when built)
- Must be a single `transaction.atomic` block. Partial finalization corrupts
  the canonical `contracts.*` tables.
- The draft is **only** deleted on full success. Any failure rolls back and
  leaves the draft intact in its prior status.
- On finalization, JSON values are shredded into real FK columns on
  `Contract`, `Clin`, `IdiqContract`, `IdiqContractDetails`,
  `ContractFinanceLine`, `ContractPackaging`. The mapping is the load-bearing
  surface — any new `data` key that needs to land somewhere on finalization
  MUST be added to the finalization shred AND to the per-type schema.

### Template changes
- Templates intentionally mirror `processing/` visually so analysts learning
  the new system see familiar UI. Don't introduce styling primitives that
  diverge from the processing app without a deliberate reason.
- The queue is a worklist, NOT a report. Resist requests to add award date,
  contract value, or buyer columns — those belong on the draft detail page.
  The queue answers "what's waiting and what do I do with it?" and nothing
  more.

### Coupling
- `intake` reads `contracts.Contract` for the "Already in DB" badge.
  Don't write to `contracts.*` from `intake` except via the (future)
  finalization path.
- No `transactions` signal coupling on `DraftContract` — drafts are
  pre-canonical.
- No `request.active_company` scoping on the queue yet (Phase 1 design
  intentionally simple). When company scoping is added it should mirror the
  pattern in `contracts.views.mixins.ActiveCompanyQuerysetMixin`.

### Editor changes (Phase 2a)
- Field name convention in `draft_edit.html` is the load-bearing contract
  with `forms_parse.parse_post`. Adding a key to a schema is **not enough** —
  the template must POST it under the right prefix (`f_*`, `clin-i-*`,
  `pkg-*`, `nsn-i-*`, `supp-i-*`, `fin-i-*`) AND the field name must be in
  the matching allowlist set in `forms_parse.py`. Skip either step and the
  field is silently dropped at POST time, not flagged at validate time.
- All write endpoints (`save_draft`, `mark_ready`, `cancel_draft`) MUST hold
  the soft lock and MUST call `assert_holds` before writing. The
  `test_save_rejects_when_user_lost_lock` test exists specifically to catch
  regressions here — don't disable it without thinking.

## Tests
`intake/tests.py` covers:
- Unique constraint on `contract_number` (dedup against re-injection)
- Per-type schema rejection of invalid `data`
- Lock acquire / release / expiry semantics
- POST → JSON parse contract (scalars, indexed rows, unknown keys, blank rows)
- Editor flow: lock gating, Save, Mark Ready, Cancel, lost-lock rejection,
  validation error surfacing, start-draft redirect to editor

After model changes:
- `python manage.py makemigrations --check`
- `python manage.py check`
- `python manage.py test intake`

## Footguns
- The `data` field defaults to `{}`. An empty dict validates against any
  schema (all keys are Optional). That is intentional — drafts may be very
  bare at queue time. Don't add `required=True` keys to root schemas without
  a clear ingestion guarantee.
- `DraftContract.save()` re-validates every save. A schema bug surfaces as
  a save failure on previously-valid records. Migrations that touch existing
  rows must round-trip through `validate_data`.
- `final_contract` is `SET_NULL` so finalized-then-deleted-Contract scenarios
  don't cascade-delete intake history (though drafts are deleted on
  finalization in practice).
