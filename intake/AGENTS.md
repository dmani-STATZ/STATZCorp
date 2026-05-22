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

### Finalization (Phase 3 — all seven types)
- The view (`finalize_draft_view`) wraps `finalize.finalize_draft` in
  `transaction.atomic()`. **`finalize.py` itself does not start the
  transaction** — it assumes the caller does. If you call `finalize_draft`
  from a management command or shell, wrap it yourself.
- All validation (matched buyer, matched NSN/supplier per CLIN, status
  guard) happens BEFORE any `objects.create()` call. This is deliberate —
  raising early avoids partial state inside the transaction even though
  the rollback would clean it up. Don't reorder.
- The draft is deleted on full success. The brief `final_contract` FK
  assignment exists for the rollback-safe audit trail; nothing reads it
  post-success because the row is gone.
- Each type has its own `_finalize_*` function. The dispatcher in
  `finalize_draft` is the only place that knows how to pick. When adding
  a type variant (or splitting one), update the dispatcher AND add a
  happy-path test in `FinalizeExtendedTypesTests`.
- JSON → canonical mapping lives in the `finalize.py` module docstring
  and the table in `CONTEXT.md`. Any new `data` key that needs to land
  somewhere on finalization MUST be added to the mapping AND to a
  `FinalizationTests` or `FinalizeExtendedTypesTests` case.
- **MOD/AMD are special**: they do NOT create a new Contract. They
  append a tagged `Note` on the matched parent and return the parent.
  The view code uses `draft_type` (captured pre-delete) to skip the
  email-compose redirect for these. If you add a new "modify existing"
  type, route it the same way.
- **finance_lines** are now nested per-CLIN in the draft JSON and
  finalized inline (`_create_clins` handles them). Root-level
  `finance_lines` is **legacy** — the backward-compat path in
  `_apply_legacy_root_finance_lines` accepts them with a warning and
  attaches to the first CLIN. Remove that path once the queue is
  confirmed clear of pre-redesign drafts.
- **ClinSplit** rows are created from per-CLIN `splits` (company_name +
  percentage). `split_value` is computed in finalize as
  `planned_gp × percentage / 100` (quantized to cents), not pulled from
  the draft. The editor renders the live value for analyst feedback.

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

### Editor changes
- Field name convention in `draft_edit.html` is the load-bearing contract
  with `forms_parse.parse_post`. Adding a key to a schema is **not enough** —
  the template must POST it under the right prefix and the field name must
  be in the matching allowlist set in `forms_parse.py`. Valid prefixes:
  `f_*` (scalar), `clin-i-*`, `clin-i-fin-j-*`, `clin-i-split-j-*`,
  `pkg-*`, `nsn-i-*`, `supp-i-*`. Skip either step and the field is
  silently dropped at POST time, not flagged at validate time.
- Nested keys (`clin-i-fin-j-*`, `clin-i-split-j-*`) require entries in
  `_NESTED_ROW_KEY` (regex) and `_NESTED_BUCKET` (allowlist map). The CLIN
  card template uses `__CLINIDX__` and the sub-templates use
  `__CLINIDX__` + `__FINIDX__` / `__SPLITIDX__`; the JS engine in
  `draft_edit.html` substitutes them on row add.
- All write endpoints (`save_draft`, `mark_ready`, `cancel_draft`) MUST hold
  the soft lock and MUST call `assert_holds` before writing. The
  `test_save_rejects_when_user_lost_lock` test exists specifically to catch
  regressions here — don't disable it without thinking.

### Matcher changes (Phase 2b/2c)
- `intake/matchers.py` is the single source of truth for what target_paths
  are valid and which match_type each one accepts. Don't widen path
  grammar without also expanding the test in `MatcherUnitTests` — the
  endpoint will accept any JSON the matchers module accepts.
- `match_endpoint` saves via `draft.save()` which re-validates the whole
  payload. A schema change that tightens an Optional → Required will
  break previously-saved drafts on the next match. Keep matcher writes
  Optional-friendly.
- `search` is intentionally **unlocked**. It only reads canonical tables
  (Buyer / IdiqContract / Nsn / Supplier) and never touches the draft.
  Don't add lock requirements there — users browse before claiming.
- The editor reloads on `intake:match-applied`. If you add async behavior
  that should not trigger a reload, dispatch a different event.
- **Inline create (Phase 2c)** — `CREATABLE_TYPES = {'buyer','nsn','supplier'}`.
  Adding a new creatable type requires three coordinated edits:
  (1) a `_create_<type>` function in `matchers.py` with explicit dedup,
  (2) adding the type to `CREATABLE_TYPES` and `CREATORS`,
  (3) a `<div data-create-fields="<type>">` field group in
  `templates/intake/_match_modal.html` AND adding the type to `CREATABLE`
  in `static/intake/js/match_modal.js`. Skip step 3 and the modal will
  silently lack a UI surface even though the endpoint accepts the
  request. **Do not expose IDIQ or Contract creation here** — they
  require fields (award_date, term_length, FK chains) that don't fit
  the modal's flat form; route analysts to the contracts app instead.
- Create runs inside the same atomic block as the immediate apply. If
  the apply or save fails, the new canonical row rolls back too. Don't
  split create and apply across requests — that re-introduces the
  "orphan row exists but isn't linked to a draft" failure mode.

### Editor field semantics (do not regress)
- **`canonical_contract_type_id` vs `contract_type`:** `contract_type` on
  `DraftContract` is the intake routing type (AWD/PO/DO/etc.) set by the
  parser — never shown as an editable field. `canonical_contract_type_id`
  in `data` is the analyst-selected ContractType FK (Bilateral/etc.) that
  lands on `Contract.contract_type` at finalization. Do not conflate them.
- **`contractor_name` / `contractor_cage`:** parser provenance fields in
  JSON only. Do **not** add them back to `draft_edit.html`. If someone
  asks to show them in the form, read this note first.
- **`item_value` vs `unit_price`:** `item_value` is the government contract
  unit price from the 1155 parser (`ingest._clin_to_dict` maps parser
  `unit_price` → `item_value`). `unit_price` is the supplier quote and is
  manual in the editor. Do not swap these in ingest.
- **PO Number:** display-only placeholder in intake. Assigned after
  finalization by processing — never add a POST field or schema key for it.

### PDF Ingestion (Phase 3c)
- `intake/ingest.py::_result_to_data` is the single mapping from
  `AwardParseResult` (parser dataclass) to the intake JSON shape. If you
  add a parser field, update the mapping AND add a test under
  `IngestUnitTests`. Don't sprinkle conversion logic in views.
- **`ia` mapping:** `ia` is derived from `ClinParseResult` in
  `_clin_to_dict`. The exact source field(s) are documented in the
  `_ia_from_clin_parse` docstring. Do not remove this mapping — it was
  previously absent and caused IA to be blank on all ingested CLINs.
- **Contract `due_date`:** derived as `min(clin.due_date)` at ingest.
  Do not remove — without it the contract-level due date is always blank
  on ingest.
- The upload view processes files independently. Do NOT wrap the batch in
  a single transaction — one bad PDF must not roll back the good ones.
- Dedup is enforced against both `DraftContract.contract_number` and
  canonical `Contract.contract_number`. Don't bypass either check, even
  for "re-import" workflows — analysts should explicitly delete a draft
  before re-ingesting its source PDF.
- The parser lives in the `processing` app and is shared. Don't fork it.
  If you need parsing behavior intake-specific, push the change upstream
  to `processing.services.pdf_parser` so processing stays consistent.

### DIBBS Ingestion
- `intake/ingest.py::ingest_dibbs_record` is the single converter from a
  scraped DIBBS row to a `DraftContract`. The scraper itself
  (`sales/services/dibbs_awards_scraper.py`) is reused as-is — do not
  fork or rewrite it.
- Drafts from DIBBS have `pdf_parse_status='no_pdf'` deliberately —
  analysts must either edit by hand OR delete the skeleton and re-ingest
  the actual award PDF. Don't change this status default; it's how the
  editor flags "incomplete data, parse failed/missing".
- The management command `intake_dibbs_pull` is the only sanctioned
  invocation path today. If you add a web button to trigger this, run it
  out-of-band (Celery / management command) — the scrape uses Playwright
  and a launched Chromium, which can take minutes per date.

## Tests
`intake/tests.py` covers:
- Unique constraint on `contract_number` (dedup against re-injection)
- Per-type schema rejection of invalid `data`
- Lock acquire / release / expiry semantics
- POST → JSON parse contract (scalars, indexed rows, unknown keys, blank rows)
- Editor flow: lock gating, Save, Mark Ready, Cancel, lost-lock rejection,
  validation error surfacing, start-draft redirect to editor
- Matcher unit tests: search shape, apply per path, type/path validation,
  clear semantics
- Matcher endpoint tests: lock gating on apply/clear, search-without-lock,
  invalid JSON / unknown action rejection

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
