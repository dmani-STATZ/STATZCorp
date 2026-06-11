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
- **One-step finalization (`finalize_direct`):** `finalize_direct_view` in
  `views.py` runs two sequential atomic transactions. TX1: parse POST →
  validate → save → set status=READY_FOR_REVIEW (lock NOT released). TX2:
  call `finalize_draft`. The lock must be held between TX1 and TX2 — do not
  release it in TX1. `finalize.py` is NOT modified — the status guard in
  `finalize_draft` still requires `ready_for_review`. If you change the status
  guard in `finalize.py`, update `finalize_direct_view` accordingly.
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
- Queue scoping uses `UserCompanyMembership` (all companies the user belongs to).
  Superusers see every non-completed draft including `company=None` rows.
  PDF upload sets `company` from `request.active_company`.

### Editor changes
- **IDIQ field visibility:** The Contract Details card hides fields
  irrelevant to IDIQ (due_date, contract_value, pr_number, plan_gross,
  planned_split, nist, po_number) using `{% if draft.contract_type != 'IDIQ' %}`
  guards. Do not remove these guards or the hidden fields will reappear
  for IDIQ drafts. Do not add new Contract Details fields for IDIQ without
  first confirming the field has a column on `contracts.IdiqContract` and
  a mapping in `intake/finalize.py::_finalize_idiq`.
- Field name convention in `draft_edit.html` is the load-bearing contract
  with `forms_parse.parse_post`. Adding a key to a schema is **not enough** —
  the template must POST it under the right prefix and the field name must
  be in the matching allowlist set in `forms_parse.py`. Valid prefixes:
  `f_*` (scalar), `clin-i-*`, `clin-i-fin-j-*`, `clin-i-split-j-*`,
  `pkg-*`, `pair-i-*` (IDIQ only). Skip either step and the field is
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
- **Supplier flag display rule (intake):** Intake is JSON-backed — there are no live Supplier ORM objects in the template. `_editor_context` builds `supplier_flags` (one DB query, `only('id','probation','conditional')`) and passes it to the template. Templates use `supplier_flags|get_item:sid` to look up flags. Apply `.supplier-flag-probation` for probation, `.supplier-flag-conditional` for conditional-only, no class for neither. Only apply when `supplier_id` is non-null. Never query Supplier inside a template — always use the pre-built `supplier_flags` context variable.

### Matcher changes (Phase 2b/2c)
- **Archived supplier exclusion:** `_search_supplier` filters
  `archived=False`. Do not remove this filter. Suppliers that were matched
  before being archived retain their `supplier_id` in the draft JSON —
  finalization still resolves them by PK. Do not add archived filtering to
  `_lookup_supplier` — lookups must succeed even for archived suppliers
  already stored in a draft.
- `intake/matchers.py` is the single source of truth for what target_paths
  are valid and which match_type each one accepts. Don't widen path
  grammar without also expanding the test in `MatcherUnitTests` — the
  endpoint will accept any JSON the matchers module accepts.
- **IDIQ pairs:** `approved_pairs` replaces the old `approved_nsns` +
  `approved_suppliers` split. Each pair row carries NSN fields, supplier
  fields, `min_order_qty`, and `supplier_part_number`. Finalization
  creates one `IdiqContractDetails` row per pair where both `nsn_id`
  and `supplier_id` are matched. `supplier_part_number` is stored as-is
  (no canonical lookup). Do not reintroduce cross-product logic.
  Do not add `supplier_part_number` to any canonical lookup table —
  it is a free-text field on IdiqContractDetails only.
  - `approved_pair:<i>:nsn` — writes NSN fields into `approved_pairs[i]`
  - `approved_pair:<i>:supplier` — writes supplier fields into `approved_pairs[i]`
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
  JSON only. Do **not** add them back to `draft_edit.html`. Supplier text
  on each CLIN is pre-populated from the inspection block at ingest; analyst
  can override via the Match button. If someone asks to show contractor
  fields in the form, read this note first.
- **`item_value` vs `unit_price`:** `item_value` is the government contract
  unit price from the 1155 parser (`ingest._clin_to_dict` maps parser
  `unit_price` → `item_value`). `unit_price` is the supplier quote and is
  manual in the editor. Do not swap these in ingest.
- **PO Number:** display-only placeholder in intake. Assigned after
  finalization by processing — never add a POST field or schema key for it.

### PDF Ingestion (Phase 3c)

The intake app owns its own PDF parser at `intake/pdf_parser.py`. It has
NO dependency on `processing.services.pdf_parser`. Do NOT re-introduce
that import. The intake parser is ported from the original processing
parser and extended with intake-specific extraction logic.

`intake/ingest.py::_result_to_data` is the single mapping from
`AwardParseResult` (intake parser dataclass) to the intake JSON shape. If
the parser grows new fields, update the mapping there AND add a test under
`IngestUnitTests`. Don't sprinkle conversion logic in views.

**Supplier drill-down:** The parser extracts supplier CAGE + name using a
two-level drill-down. Contract-level "PLACE OF INSPECTION FOR SUPPLIES"
establishes the default. CLIN-level occurrence overrides per CLIN. If
neither level has the block, supplier fields are None and the analyst fills
manually. Do NOT use contractor_cage / contractor_name (Block 9 prime
contractor) as supplier fallback — they are different entities.

**Packhouse drill-down:** Same pattern. Contract-level "PLACE OF INSPECTION
FOR PACKAGING" is the default. CLIN-level overrides per CLIN.

**IDIQ supplier extraction:** `_extract_idiq_supplier_via_claude_api`
sends Section B text to the Claude API (same pattern as
`_extract_clins_via_claude_api`) and returns supplier_name, cage,
part_number as a JSON object. Called only when contract_type == 'IDIQ'.
Must use `_section_b_slice(text)` as input — never full document text —
to avoid matching the prime contractor in Block 9. Returns None on
failure; ingest handles None gracefully (no approved_pairs populated).
part_number is optional and may be null.

**`ia` mapping:** `ia` is derived from `ClinParseResult.inspection_point`
only (not acceptance). ORIGIN → 'O', DESTINATION → 'D'.

**`item_value` vs `unit_price`:** `item_value` is the government contract
unit price. `unit_price` is the supplier quote — manual entry only, never
parsed from PDF.

**Contract `due_date`:** derived as `min(clin.due_date)` at ingest. Do not
remove.

The upload view processes files independently. Do NOT wrap the batch in a
single transaction.

Dedup is enforced against both `DraftContract.contract_number` and
canonical `Contract.contract_number`.


### SharePoint Integration Rules

- Intake owns its own SharePoint service at `intake/services/sharepoint_intake.py`.
  Do **NOT** import SharePoint helpers from `processing.*`.
- `build_draft_folder_path(draft)` is the single source of truth for draft folder
  paths. Drafts are always open-contract paths — no Closed/Cancelled routing at
  draft time. Contract number is normalized to dashed format inside this function as a
  defensive measure before the path is assembled.
- `probe_draft_sharepoint_folder(draft)` — probe only, no create.
- `create_draft_sharepoint_folder(draft)` — probe first, create if missing. Called
  at PDF upload time only.
- SharePoint folder path is stored in `draft.data['sharepoint_folder_path']`
  (JSON). It is **not** a model column.
- `sharepoint_folder_status` is a real model column
  (`pending` / `exists` / `not_found` / `created` / `error`).
- Company lookup at DIBBS injection uses `sales.CompanyCAGE` (`dibbs_company_cage`)
  CAGE code join. If no company found, `draft.company=None` and SP probe is
  skipped.
- At finalization, copy `draft.data.get('sharepoint_folder_path')` →
  `contract.files_url` for all Contract-creating types
  (AWD/PO/DO/IDIQ/INTERNAL). Skip for MOD/AMD (they modify existing contracts
  that already have `files_url`).
- Scan endpoint: `intake:scan_sharepoint_drafts` at POST `/intake/api/scan-sharepoint/`. Body: `{"draft_id": N}` or `{"all": true}`. Returns `results` array with per-draft status.
- Scan is company-scoped: non-superusers filtered to their membership companies. Superusers see all.
- Folder creation at PDF upload: `create_draft_sharepoint_folder(draft)` is called inside `upload_pdfs` after successful `ingest_pdf`. It is non-blocking and does not affect the HTTP response status.
- Do NOT call `create_draft_sharepoint_folder` at DIBBS injection time — probe only (`probe_draft_sharepoint_folder`).
- The "Scan SP" bulk button only scans drafts with `sharepoint_folder_status` in `['pending', 'error', 'not_found']`. It does not re-probe already confirmed `exists`/`created` folders.
- Draft documents browser lives at `contracts:intake_draft_documents_browser` (`/contracts/documents/draft/`). It reuses `contracts/documents_browser.html` with `is_draft_mode=True` context. Do not create a separate template.
- Authorization gate for draft browser: `_draft_for_request()` in `contracts/views/documents_views.py`. Non-superusers must have membership in `draft.company`.
- All file API endpoints (list, upload, download, delete, folder weburl, create folder) now accept `draft_id` as an alternative to `contract_id` for the authorization gate. The actual path resolution is always `folder_path`-based and does not use the contract/draft FK.
- `set_draft_file_path_api` (POST `/contracts/api/drafts/set-file-path/`) saves the confirmed path to `draft.data['sharepoint_folder_path']` and sets `sharepoint_folder_status = 'exists'`.
- Finalization carry-through: `_draft_to_service_payload` and `_finalize_idiq` both fall back to `data['sharepoint_folder_path']` when `data['files_url']` is empty. This is the zero-extra-step path from SP probe → finalization.
- MOD/AMD finalization does NOT carry through `files_url` — they modify existing contracts that already have their own `files_url`.

### DIBBS Ingestion
- `intake/ingest.py::ingest_dibbs_record` is the single converter from a
  scraped DIBBS row to a `DraftContract`. Row data is supplied by
  `intake/services/queue_we_won_drafts.py`, which maps `DibbsAward` ORM
  fields to the scraper dict shape — do not fork conversion logic elsewhere.
- `_dibbs_contract_number(record)` always returns a normalized (dashed) DLA
  contract number by calling `normalize_contract_number()` before returning.
  The raw DIBBS field values (`Award_Basic_Number`, `Delivery_Order_Number`) are
  NOT modified — they are used separately by `_build_dibbs_award_pdf_url()`
  for HTTP URL construction and must remain undashed.
- Drafts from DIBBS have `pdf_parse_status='no_pdf'` deliberately —
  analysts must either edit by hand OR delete the skeleton and re-ingest
  the actual award PDF. Don't change this status default; it's how the
  editor flags "incomplete data, parse failed/missing".
- DIBBS skeleton drafts are created automatically by the `scrape_awards`
  WebJob piggyback (`queue_we_won_drafts`), immediately after
  `queue_we_won_awards`. Do not add a separate scrape path; the daily job
  already owns Playwright and batch-scoped we-won filtering.

### DIBBS PDF Fetch (On-Demand)

intake/services/dibbs_pdf_fetcher.py::fetch_and_apply_dibbs_pdf(draft) is the
single entry point for fetching, parsing, and merging a DIBBS PDF. Call only from
fetch_dibbs_pdf view  never from the nightly scraper.
DIBBS award PDF URL pattern: Award/IDIQ/PO  dibbs2.bsm.dla.mil/Downloads/Awards/ {DDMONYY}/{contract_number}.PDF; DO  {award_basic_number}{do_number}.PDF.
Date folder = Award Date (not Posted Date), formatted as zero-padded DD + 3-letter
month + 2-digit year (e.g., 28MAY26).
draft.data['award_pdf_url'] is stored at DIBBS injection time for all new
skeletons. Old skeletons fall back to DibbsAward ORM lookup in _resolve_pdf_url.
draft.data['award_basic_number'] is stored at injection time for DO/IDIQ drafts.
Download uses make_dibbs2_session() from sales.services.dibbs_session  this
handles the DOD Computer Use Notice cookie for dibbs2.bsm.dla.mil. DO NOT use
make_www_session() (wrong domain). DO NOT import from processing.*.
After fetch: merge_parsed_pdf_into_draft(draft, parse_result) in intake/ingest.py
replaces all draft.data keys with the parsed result (parsed data wins). The
award_pdf_url key is re-seeded from the original skeleton data after merge so it
survives for audit.
SharePoint upload is non-blocking: SP failure does not mark the overall operation
as failed.
DraftContract.is_dibbs_draft property: True when data['parser']['source'] == 'dibbs'.
After a successful fetch and merge, parser.source becomes 'pdf', so the button
naturally disappears on next page load.

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
