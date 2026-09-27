# AGENTS_quote.md — `quote` App

> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership,
> shared infrastructure, and cross-boundary change rules.

## 1. Purpose of This File
How to change the `quote` app safely. Read `CONTEXT_quote.md` first for what the app *is*;
this file is not a repeat of it.

## 2. App Scope
- **Owns:** all quoting workflow data — `QuoteSolicitation`, `QuoteSupplierNSN`,
  `QuoteSupplierFSC`, `QuoteSolicitationMatch`, `QuoteRFQ`, `QuoteSupplierQuote`, `QuoteBid`,
  `QuoteEmail`, `QuoteEmailAttachment`, `QuoteEmailSolLink`, `BidOutcome`. All `quote_*` tables.
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

## 5. Files That Commonly Need to Change Together

### Adding a field to a quote model
`quote/models/<module>.py` + migration + `quote/models/__init__.py` (if a new model) +
the relevant form/service/template + `CONTEXT_quote.md` §5.

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
