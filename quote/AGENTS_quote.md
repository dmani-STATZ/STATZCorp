# AGENTS_quote.md — `quote` App

> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership,
> shared infrastructure, and cross-boundary change rules.

## 1. Purpose of This File
How to change the `quote` app safely. Read `CONTEXT_quote.md` first for what the app *is*;
this file is not a repeat of it.

## 2. App Scope
- **Owns:** all quoting workflow data — `QuoteSolicitation`, `QuoteSupplierNSN`,
  `QuoteSupplierFSC`, `QuoteCapabilityImport`, `QuoteSolicitationMatch`, `QuoteRFQ`,
  `QuoteSupplierQuote`, `QuotePackhouseRFQ`, `QuoteBid`, `QuoteEmail`, `QuoteEmailAttachment`,
  `QuoteEmailSolLink`, `BidOutcome`. All `quote_*` tables.
- **Owns operationally:** solicitation pipeline state, supplier matching, RFQ dispatch,
  supplier quote entry and cost buildup, bid staging, BQ file generation, post-award
  reconciliation and the "Our Bids" analytics.
- **Does not own:** DIBBS file ingestion, solicitation records, approved sources, award
  ingestion, `CompanyCAGE` (all `dibbs`); the supplier directory (`suppliers`); part
  records (`products`).
- **App type:** feature app; read-only consumer of the `dibbs` tables, subscriber to
  `dibbs.signals.import_completed`.

## 3. Read This Before Editing

### The one rule that defines this app
**`quote` owns all of its data and never writes a `dibbs` table.** Not `Solicitation.status`
(legacy, frozen), not `DibbsAward`, not `CompanyCAGE`. Every workflow state lives on a
`quote_*` table keyed to the solicitation or line. If you want to flag a solicitation, add a
field to `QuoteSolicitation` (or a new quote model) instead. And `dibbs` must never import
from `quote` — the only link that direction is the `import_completed` signal.

The single sanctioned cross-app write is `products.Nsn`'s dimension fields
(`unit_weight`, `unit_length`, `unit_width`, `unit_height`, `dimension_source_notes`,
`dimensions_last_verified`) from the freight sub-modal. Nothing else on `Nsn`, and nothing on
`suppliers.Supplier`.

### Before changing models
- `db_table` is explicit on every model and starts with `quote_`. Never let Django auto-name.
- `models/__init__.py` re-exports every model; add new ones there or `from quote.models import X`
  breaks.
- Money types: unit prices `Decimal(13,5)`, totals `Decimal(15,2)`, percentages `Decimal(5,2)`.
  **Never `float` in a price path** — `unit_price` feeds a fixed-width government file.
- `AuditModel` lives in `models/base.py` with `quote_%(class)s_*` related names. Do not import
  another app's `AuditModel`.

### Before changing views
- `@login_required` on every view, always. Middleware is not sufficient — global behavior varies
  with `settings.REQUIRE_LOGIN`.
- Business logic goes in `quote/services/`. Views orchestrate; they do not parse, price or export.
  (`suppliers` is the repo's cautionary tale of logic-in-views.)

### Before changing templates
- Extend `quote/templates/quote/base.html`, never `base_template.html` directly — the global base
  exposes only `body` and `extra_js`, with no `content` block.
- Pass `section` in the view context or the sub-nav highlight breaks.
- HTMX/fetch fragment partials must **not** use `{% extends %}`.

### Before changing urls.py
`app_name` must stay exactly `'quote'`. `STATZWeb/middleware.py` does
`resolved.namespace.split(':')[0]` and looks that string up in `users.AppRegistry`. Change it and
permission gating silently stops applying.

## 4. Local Architecture / Change Patterns
- **Business logic location:** `quote/services/`.
- **Cost buildup:** one Decimal-only service, single source of truth. The retired `sales`
  prototype duplicated its markup formula in five views and mixed `float` into the `Decimal`
  path. Do not repeat that.
- **Status transitions:** on `QuoteSolicitation` via `set_status()` (stamps `status_changed_at`).
  Matching may only move `UNMATCHED → MATCHED`; it must never rewind a worked solicitation.
- **Reacting to new DIBBS data:** the `import_completed` receiver in `quote/signals.py`. It runs
  synchronously inside the import; keep it set-based and fast. A receiver exception is logged
  and swallowed by `dibbs`, so the import still succeeds — check logs if state looks stale.
- **Auto-created rows:** a model whose rows are created for every solicitation automatically
  must set `dibbs_disposable = True`, or dibbs' import-batch delete will refuse to remove any
  solicitation. Rep-created rows (RFQs, quotes, bids, email links) must NOT set it.
- **Concurrency:** claim fields plus a self-scheduling `setTimeout` poll. There are no websockets in
  this repo; do not add Channels without an explicit architecture decision.

### Supplier capabilities (NSN / FSC lists)
- **All writes go through `services/capabilities.py`** (`commit_plan`, `remove_capabilities`,
  `undo_import`) or `services/matching.add_manual_match`. Never `QuoteSupplierNSN.objects.create`
  in a view or another app: the write must be followed by a re-match (add) or
  `prune_derived_matches` (remove), or the queue silently drifts from the lists.
- `build_plan` is a dry run and must never write. `preview_matches` and `match_solicitations`
  share `_index_lines` / `_wanted_matches`; change matching semantics there, once.
- `prune_derived_matches` only touches open solicitations in `MATCHING_STATES`, only
  NSN / FSC links (never MANUAL), and only the affected suppliers. Keep it that way: a
  worked solicitation's history is not the lists' to rewrite.
- Parsing is server-side only. The browser posts the paste / file to the preview endpoint
  and re-posts it to commit; do not add a second parser in JS.
- The editor (`_editor.html`) is a fragment shared by the Capabilities drawer, the
  workspace drawer and the supplier detail page. `live-top` / `live-bottom` are re-rendered
  after each change; the importer between them keeps its state. Keep those `data-role`s
  stable, and keep the fragment free of inline `<script>` (it is inserted via `innerHTML`).
- Supplier-page users need Quotes access to edit: gate embeds with
  `services.access.user_can_use_quote`, not by hiding the URL.

### Supplier Research (`services/supplier_research.py`)
- Reads **`dibbs.DibbsAward`** filtered by `awardee_cage` for **any** CAGE. Never query
  **`dibbs_we_won_awards`** / **`WeWonAward`** for this feature.
- **`SupplierNSNCapability`** / **`supplier_nsn_capability`** are off-limits — use
  **`dibbs.ApprovedSource`** (`tbl_ApprovedSource`) only.
- Excel exports must write NSN, part number, CAGE, and contract/award number cells as **text**
  (`data_type = 's'`, `number_format = '@'`) so Excel does not corrupt undashed NSNs.
- Service functions return **materialized** `list` / `dict` data — no querysets, no `.iterator()`.
- **`supplier_research` (the page view) is a shell: no service calls.** Data comes from
  `supplier_research_panel`, one fragment per panel. `?refresh=1` only means something on `sam`.
- Every award read goes through **`_award_queryset()`**, which excludes `is_faux=True` (placeholder
  rows from MODs that arrived before their award). Don't add a path that bypasses it.
- Dedupe awards with `.values(*AWARD_DEDUPE_FIELDS).distinct()`; compute counts and totals from
  that set. Notice ID / sol number are unique per row, so they must not be added to the values.
- **MSSQL:** on a `.distinct()` query, every `order_by` field must also be in `.values()`.
- "Award data current through" = `Max(posted_date)` with `posted_date <= today`. Never `award_date`.
- `get_sam_entity` returns `state` = `ok` / `not_found` / `error`. Keep them distinct: a lookup
  failure (`fetch_error=True`) is not "no record", and its retry must go through
  `get_or_fetch_cage(force_refresh=True)`. Do not edit `dibbs/services/sam_entity.py` for this.
- Panel JS must not inject a response that was redirected or non-OK (login page in a card).
- **`get_open_solicitations` (the `sols` panel) is read-only.** It reads `QuoteSupplierNSN` and
  never writes it, and calls no write path in `services/capabilities.py` / `matching.py`. NSNs are
  compared via `nsn_query_variants()`; `__in` lookups run in chunks of `NSN_IN_CHUNK` (500) because
  SQL Server rejects > 2,100 parameters. Use `.values()` on lines, not `select_related` on the
  solicitation (that drags `pdf_blob`). Est. Value: call `queue.latest_unit_costs`; don't add a
  second price lookup. "Open" = `return_by_date >= today`, deliberately with no status filter.
- `get_sam_entity` returns `fields` (dict), not `rows`. Empty fields and empty groups are omitted
  by the template; `registration_expiry` is a `date` or, if unparseable, the raw string (no badges).
- Chip styling in dark mode: `text-bg-light` stays bright white, so classification chips use
  `bg-body-secondary text-body border`.

### The Phase 2 drawer form (`templates/quote/mailbox/inbox.html`)
- **It is one form shared by every SOL in the message.** All per-SOL state goes through
  `snapshot()` / `applyDraft()` / `resetForm()` (field list: `TEXT_FIELDS`). Add a drawer input
  without adding it there and it will carry over from one SOL to the next, which silently prices
  the wrong SOL. Test by switching SOLs with a value typed.
- Quantity-dependent amounts (packaging / freight totals) must be re-derived whenever the basis
  quantity changes: `renderLines()` does it through `rederive()`. Anything new that depends on
  quantity belongs there too.
- `services/cost.build` remains the only price authority; the drawer is a preview. Keep the JS and
  server formulas identical (markup on cost, totals ÷ combined quantity).
- Drafts are `localStorage`; after a successful save `draftsLocked` stops the autosave from writing the
  SOL's draft back before the message reloads.

### One quote per supplier per line, and quotes from anywhere
- **Only `save_supplier_quote` / `update_supplier_quote` / `delete_quotes` may write a rep's
  `QuoteSupplierQuote` rows.** Saving *updates* the supplier's row on a line if it has one (from any message
  or channel); it never adds a second. Do not `QuoteSupplierQuote.objects.create` from a view, a task or an
  import: it bypasses the lock, the bid sync and the one-per-line rule.
- The rule is enforced in the service, not by a unique constraint (older data may hold duplicates). If you
  add a constraint, ship a cleanup first.
- A quote's source is `source_email` (a mailbox message) **or** `source_channel` phone / fax / web / other with
  `received_on` / `contact_name`. Manual entry requires a channel at the view (`views/quotes.quote_save`); the
  service defaults a blank one to OTHER so scripts and tests do not have to say.
- **The tray is shared.** `quote-drawer.js` and `mailbox/_tray.html` serve both the mailbox and the Quotes
  page. Anything mailbox-only (the split viewer, docking, `quoteMailbox.reload`) stays in `mailbox/inbox.html`;
  anything tray-wide goes in `quote-drawer.js` behind `cfg` (`onSaved`, `searchUrl`, `phCtx`). Manual-only
  fields exist only when `manual=True` and every script path must tolerate their absence.
- The tray's size is one knob: `--quote-drawer-scale` (currently `0.9`, applied as CSS `zoom` on the drawer body in
  `app-core.css`). Do not shrink it with per-element font sizes, and do not touch page-wide sizing for it.
  Anything that measures the drawer's width (the split-screen dock) must read the resting edge, not mid-slide.
- There is no "ready for DIBBS" trigger to add. Phase 3 lists a solicitation once it has a quote; the rep's step is
  **Save & mark ready** in the bid builder. The Quotes page's Bid column only links to that step.
- A new quote names its lines with `line_ids` (only lines the supplier has not quoted); do not rely on
  `mode=combined`, which means "every line" and would update quotes already on file.
- The Quotes page's waiting list is derived from `QuoteRFQ` rows and quotes; nothing else stores "waiting".
  Closing a supplier out changes RFQ status only. `delete_quotes` must never remove a quote a bid rests on.

### Editing a logged quote
- **One save = one entry.** `save_supplier_quote` writes a row per line and stamps them all with the same
  `entry`; the drawer edits that group as one quote. Never write `QuoteSupplierQuote` rows for a rep's
  quote outside `save_supplier_quote` / `update_supplier_quote`, or the drawer cannot find them.
- **Update in place, never delete-and-recreate.** Bids point at quote rows (`QuoteBid.selected_quote`);
  replacing rows would null those links. `update_supplier_quote` keeps the primary keys.
- **The lock is `QuoteBid.SUBMITTED` on a bid whose `selected_quote` is any row of the entry.** Enforce it
  in the service (`QuoteLockedError`), not only in the UI. Anything else that mutates a quote's price
  or days (a new edit path, an import) must go through the same check and call
  `bids.sync_after_quote_edit`.
- `sync_after_quote_edit` must never touch a SUBMITTED bid; it only follows numbers the bid still
  carries from the quote and demotes READY -> DRAFT (and `BID_READY` -> `QUOTING`) when something a
  bid depends on changed.
- The drawer payload's `cards` are the contract with `inbox.html` (`applyCard`, `cardLabel`,
  `applyCardState`): change the keys in `services/quotes._card` and those together.
- `{# #}` template comments must be **one line**. A wrapped one is printed on the page. A test
  (`TemplateSyntaxLeakTests`) fails the build if template syntax reaches the browser; use
  `{% comment %}` for anything longer.

### Attachment viewer
- `attachment_view` decides the content type from the **bytes** (`mailbox.sniff_preview_type`), never
  from the name or the sender's content type. PDFs and raster images only, **never SVG**. Everything
  else is 415; the download route is unchanged.
- It is the only quote view that may be framed (`@xframe_options_sameorigin`); the site default is
  `DENY`. Don't relax `X_FRAME_OPTIONS` globally for this.
- The PDF `<iframe>` has no `sandbox` attribute on purpose (browsers won't run their PDF viewer in a
  sandboxed frame). Don't add one without re-testing a PDF in real Chrome. The message body iframe
  keeps its sandbox.
- The quote drawer is docked (`data-bs-backdrop="false"`, `data-bs-scroll="true"`) so the message and
  viewer stay readable while typing. Measure its *resting* edge (`clientWidth - offsetWidth`), not
  `getBoundingClientRect()`, which is mid-slide when Bootstrap's `shown` timer fires early.

### Packhouse quote requests
- **Not `QuoteRFQ`.** `QuoteRFQ` is the part-supplier ledger and its send path moves the
  solicitation to `RFQ_SENT`; a packhouse request must never do that. Packaging requests live in
  `QuotePackhouseRFQ` only. Don't add a `kind` flag to `QuoteRFQ` to save a table.
- **All sends go through `services/packhouse.send_requests`** (it owns the duplicate check, the
  recipient rule and the write-only-on-success rule). A failed send must leave no row.
- **One weight / dimensions block.** The drawer has a single set of `dim_*` inputs; Packaging and
  Freight only read it out (`[data-dims-readout]`). Don't add a second set of inputs to either
  section: two copies drift, and only one can be written to `products.Nsn`.
- `record_reply` is the only writer of `quoted_*`. It derives the unit price from the total over the
  quantity *asked about* (`QuotePackhouseRFQ.quantity`), not the drawer's current scope, and bounds both
  values to their columns before saving.
- The reply hook lives in `services/mailbox.mark_rfqs_responded` (needs `sent_at <= received_at`).
  `mailbox.py` reads the model directly rather than importing `services/packhouse`, to keep the
  import graph one-way.
- The drawer JS keeps the request list in the fragment's `quoteDrawerData`; sends update it in place.
  Don't call `window.quoteMailbox.reload()` after a send: it re-fetches the fragment and wipes the
  rep's half-entered quote.

## 5. Files That Commonly Need to Change Together

### Changing the packhouse request flow
`quote/services/packhouse.py` (rules, message) → `quote/views/packhouse.py` (JSON shape) →
`quote/static/quote/js/packhouse.js` (renders `preview_request` / `serialize` output; keys are a
contract) → `templates/quote/mailbox/_detail.html` (panel + banner) and `inbox.html` (`applyQuote`,
dims read-out) → `quote/tests/test_packhouse.py` → `CONTEXT_quote.md` §6 Phase 2.

### Adding a field to a quote model
`quote/models/<module>.py` + migration + `quote/models/__init__.py` (if a new model) +
the relevant form/service/template + `CONTEXT_quote.md` §5.

### Changing the capability importer or editor
`quote/services/capabilities.py` (rules) → `quote/views/capabilities.py` (payload / JSON shape) →
`quote/static/quote/js/capabilities.js` (renders `plan_to_preview` output; keys are a contract) →
`quote/templates/quote/capabilities/*` → `quote/tests/test_capabilities.py` → `CONTEXT_quote.md` §6.
The supplier detail page (`templates/suppliers/supplier_detail.html`, `#section-capabilities` +
the `sectionIds` scroll-spy list) and the workspace supplier cards consume the same fragment.

### Adding a page
`quote/views/<module>.py` + `quote/views/__init__.py` + `quote/urls.py` +
`quote/templates/quote/<page>.html` + a sub-nav entry in `quote/templates/quote/base.html` +
`CONTEXT_quote.md` §12.

### Adding a background task
`quote/tasks/<name>.py` + `TASK_FUNCTIONS` in `core/management/commands/run_background_tasks.py` +
a `core.ScheduledTask` data migration. **All three, or it silently never runs.**

### Adding a CSS class
`static/css/app-core.css` only. Shell/sub-nav classes are shared (`.app-shell`, `.app-subnav*`).
Never a new CSS file.

## 6. Cross-App Dependency Warnings

**This app depends on:** `dibbs` (solicitations, lines, `bq_raw_columns`, approved sources,
awards, `CompanyCAGE`, `SAMEntityCache`, `competitor_stats`, `import_completed` signal),
`suppliers` (`Supplier`, `Contact`, packhouse flags), `products` (`Nsn` dimensions),
`mailer` (`graph_mail.send_mail_via_graph`), `core` (`ScheduledTask`), `users`
(`AppRegistry` / `AppPermission`).

**Other apps that depend on this app:** `core` global search (`QuoteSolicitationMatch`,
`QuoteRFQ`), `products` NSN/supplier pages (`QuoteSupplierQuote`, `QuoteBid`,
`QuoteSupplierNSN`). Renaming those fields breaks them.

**URL namespace:** `quote:` — referenced from `templates/base_template.html` (one sidebar `<li>`).
That file is a shared contract; changing `quote:dashboard` breaks it.

## 7. Security / Permissions Rules
- `@login_required` everywhere.
- `QuoteEmail.body_html` and attachment bytes are supplier-supplied. Render HTML only in a sandboxed
  no-scripts iframe. Never trust an attachment's `content_type`.
- No `company` FK on quote data by design — scope by CAGE via `dibbs.CompanyCAGE`.
- Export/download endpoints are sensitive: keep access controls and expected columns intact.

## 8. Model and Schema Change Rules
- `makemigrations --check` must be clean after any model edit.
- Migrations must work on **both** SQL Server (prod/dev) and SQLite (CI).
- **No MARS in data migrations.** Never `.iterator()` or iterate a lazy queryset while writing on the
  same connection. Materialize with `list(qs.values(...))`, batch writes at 500 or fewer inside
  `transaction.atomic()`.
- **Bulk inserts:** chunk `bulk_create` at 200 rows (the size the dibbs importer uses in
  production). For whole-table backfills use one set-based `INSERT … SELECT` (see `0004`).
  Never `bulk_create` a model with an `auto_now_add` NOT NULL column on SQL Server (8115).
- Chunk every `__in` lookup under SQL Server's 2,100-parameter limit.
- Quote migrations never alter `dibbs` tables. (If you ever must touch `dibbs_award`, use
  `dibbs.db_objects.drop_we_won_awards_view` / `recreate_we_won_awards_view` around it.)
- `Cast(...)` on a CharField needs the `TRY_CAST` vendor guard.

## 9. View / URL / Template Change Rules
- Keep `app_name = 'quote'`.
- No CDN `<link>` / `<script>` tags in quote templates — the app is served under GCC High CSP.
  jQuery, jQuery UI and the Bootstrap 5.3.3 bundle are already loaded in the global base's head.
- No Tailwind classes. Bootstrap 5 utilities or named classes in `app-core.css`.
- Drawers: Bootstrap `offcanvas-end`. Modals: `bootstrap.Modal`. Toasts: `window.showToast`.
- Dark mode: `[data-bs-theme="dark"] .class`. Never `.dark` or `body.dark`.
- Pollers: self-scheduling `setTimeout` chain, never `setInterval`.

## 10. Forms / Input Validation Rules
- Validate numerics as `Decimal`, never `float`.
- BQ field widths are contractual: `unit_price` 5 decimals, `delivery_days` a whole positive integer,
  `bid_remarks` at most 255 chars, CAGE codes exactly 5.

## 11. Background Tasks / Automation Rules
- Task callables take no arguments and handle their own partial failure.
- `ScheduledTask.name` must match the `TASK_FUNCTIONS` key exactly, case-sensitive.
- Seed the row by data migration so it exists in every environment.
- **No Django ORM calls inside `with sync_playwright():`** — the mssql driver's cached
  `sql_server_version` opens a temporary connection and raises `SynchronousOnlyOperation` inside
  Playwright's event loop.

## 12. Testing and Verification Expectations
| Change area | Verify |
|---|---|
| Models | `python manage.py makemigrations --check`, `python manage.py test quote` |
| Cost buildup | Decimal equality on landed cost and final price; no `float` anywhere |
| BQ export | Byte-level diff against a known-good DIBBS-accepted `bq` file |
| Mailbox | Auto-SOL detection, one-email-to-many-SOL linking, attachment download |
| Permissions | Log in as a non-superuser with and without an `AppPermission` row |
| Templates | Both light and dark theme; confirm the sub-nav highlight |

Baseline: `python manage.py check`, `python manage.py test quote dibbs products core`.

## 13. Known Footguns
1. **`quote` is deny-by-default.** `0002` created its `AppRegistry` row, so every non-superuser
   needs an explicit `AppPermission(has_access=True)` or they hit `permission_denied`. There is
   no signal backfilling permissions for new users (`users/signals.py` has it commented out).
2. **`app_name` drift silently disables permission checks.** See §3.
3. **`base_template.html` has no `content` block.** Extending it directly renders a blank page.
4. **`dibbs.SolicitationLine` has no unique constraint on `(solicitation, nsn)`** even though the
   dibbs importer keys its diff on that tuple. Do not assume that pair is unique.
5. **`bq_raw_columns` can legitimately be `NULL`** on a line imported before a BQ file existed for
   it. The BQ writer must produce a clear error, not a traceback.
6. **Historical `bq_raw_columns` rows may contain `U+FFFD`.** They were written while the importer
   decoded the ISO-8859-1 file as UTF-8. The decode is fixed, but existing rows only heal on
   re-import — the original bytes are gone.
7. **`DibbsAward` has no quantity and no unit price.** Award unit price is always derived from
   `total_contract_price` and the solicitation line quantity, which is an approximation on
   multi-line awards. Never present it as a published DIBBS figure.
8. **`QuoteBid.line` is OneToOne.** Combined-CLIN pricing writes several bids sharing a
   `clin_group`; it does not write one bid spanning lines.
9. **`QuoteSolicitation` rows are seeded, not guaranteed.** Every imported solicitation gets one
   via the import signal (and `0004` backfilled history), but a failed receiver is only logged.
   Code that reads `solicitation.quote_state` must handle `RelatedObjectDoesNotExist`, or call
   `services.matching.seed_solicitation_states([...])` first.
10. **`send_mail_via_graph` returns `False` on failure, it does not raise.** Check the return value.
11. **GCC High endpoints only** — `graph.microsoft.us`, not `graph.microsoft.com`.
12. **`is_packhouse` is a hint, not a filter.** Use the documented `Q(...) | Q(...)` OR pattern so a
    supplier who does packaging without the flag set still appears.
13. **`seed_quote_demo` writes fake solicitations, awards and suppliers.** It is deliberately a
    management command rather than a data migration so it cannot run on deploy, and it refuses to
    run when production is detected. If you extend it, every new row must carry a demo tag and
    `_clear()` must delete it — an untagged row becomes permanent litter in a prod-like dev database.
    Never make it modify a pre-existing row in a shared table (`contracts_nsn`, `contracts_supplier`):
    modifying implies deleting on `--clear`, and that would destroy real data.

## 14. Safe Change Workflow
1. Read `CONTEXT_quote.md`, then this file.
2. For anything crossing into `dibbs` / `suppliers` / `products`, read that app's `CONTEXT_` and
   `AGENTS_` pair too.
3. Make the change in `quote` first; update downstream consumers in the same change.
4. `python manage.py check` and `python manage.py makemigrations --check`.
5. `python manage.py test quote` plus the tests of any app you touched.
6. Update `CONTEXT_quote.md` when the surface changes.
7. Ship a release note (§16).

## 15. Quick Reference
- **Primary files:** `models/`, `services/`, `views/`, `urls.py`, `templates/quote/base.html`
- **Coupled areas:** `dibbs` tables (read-only) + `import_completed` signal, `suppliers.Supplier`, `products.Nsn`
  dimensions, `mailer.services.graph_mail`, `core` task registry, `users.AppRegistry`
- **Security-sensitive:** inbound email HTML and attachments, BQ export download, permission gating
- **Riskiest edits:** anything that writes a `dibbs` table; the import signal receiver; the BQ writer; migrations on
  `contracts_nsn`

## 16. Release Notes (Changelog) Rules
Any user-facing or significant change ships a release note. Strict, validated format:

- File: `release_notes/YYYY-MM-DD-short-slug.md`
- YAML frontmatter with `id` **exactly matching the filename stem**
- `published: false` on dev branches
- ISO `publish_date`
- `critical` boolean
- **`tags` must be exactly two strings**: one change type (`new` | `improved` | `fixed` |
  `breaking`) plus one area (`contracts` | `finance` | `sales` | `training` | `system`).
  Invented tags mean the file is silently skipped on deploy. **For `quote`, the area tag is `sales`.**

## 17. CSS / Styling Rules
Three CSS files repo-wide: `static/css/theme-vars.css` (brand tokens),
`static/css/app-core.css` (components and layout — new quote classes go here),
`static/css/utilities.css`. No new CSS files. No Tailwind in any form. Prefer semantic classes
(`card`, `card-padded`, `label`, `row-between`, `btn-outline-brand`) over repeated utility stacks.
Sidebar, header, toast and modal systems are hands-off — add to them, do not restructure them.

## Links that open another tab
Reference lookups reuse one named tab per destination instead of `_blank`:
`statz_sam`, `statz_dla_cage`, `statz_entity`, `statz_sol_pdf`,
`statz_dibbs_data`. Do **not** add `rel="noopener"` to these -- Chrome then
opens an isolated tab it can never find by name again, and tabs pile up. Use
named targets only for trusted destinations (.gov sites, our own pages); links
to scraped or user-supplied URLs (notice links, company websites) stay
`target="_blank" rel="noopener noreferrer"`.

## BQ writer rules (Phase 3)
- Never pad or trim DIBBS template cells; overwrite only the columns in
  `services/bids.BID_COLUMNS` / `CAGE_COLUMNS`. DIBBS pre-fills defaults in the
  template that must survive (the retired sales writer padded every field --
  do not copy it).
- Unit price: Decimal, formatted `f"{price:.5f}"`. No float, no `$`.
- A change to the file format (quoting, line endings, encoding) needs a diff
  against a DIBBS-accepted `bq` file before it ships.
- Export is all-or-nothing: any pre-flight error blocks the whole file.
