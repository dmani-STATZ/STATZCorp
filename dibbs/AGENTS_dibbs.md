# AGENTS_dibbs.md — `dibbs` App

> **Cross-app work?** Read `PROJECT_CONTEXT.md` first. Read `CONTEXT_dibbs.md`
> for what this app is; this file is how to change it safely.

## 1. Scope
- **Owns:** DIBBS-sourced data — solicitations, lines, approved sources, import
  batches/jobs, awards + mods + staging, procurement history, packaging, PDF
  analyses, notices, SAM cache, competitor intel, `CompanyCAGE`.
- **Does not own:** any quoting workflow (status pipeline, matching, RFQs, quotes,
  bids, mailbox) — that is `quote`. Suppliers (`suppliers`), contracts (`contracts`).

## 2. The rule that defines this app
**`dibbs` never imports from `quote`** (or any future sales/quoting system). It
publishes data and fires `dibbs.signals.import_completed`; consumers subscribe.
Do not add workflow columns to `dibbs_*` tables — put them on a consumer-owned
table keyed to the solicitation/line.

## 3. Before changing models
- Every model has an explicit `db_table`. Many are legacy names (`tbl_ImportBatch`,
  `tbl_ApprovedSource`) — never rename casually; SQL objects reference them.
- Money: unit prices `Decimal(13,5)`, totals `Decimal(15,2)`. No `float` in price paths.
- `makemigrations --check` must be clean on **both** SQLite and SQL Server.
- Any migration that alters `dibbs_award` must call
  `db_objects.drop_we_won_awards_view` before and `recreate_we_won_awards_view`
  after (SQLite rebuilds the table and the view blocks it).
- Drop the `DF_dibbs_award*` URL default constraints
  (`db_objects.drop_url_defaults`) before any AlterField/RemoveField on the four URL
  columns of `dibbs_award` / `dibbs_award_staging`, or SQL Server rejects it.
- Do not drop `Solicitation.status` until `usp_process_award_staging` stops
  filtering on it.
- A consumer model whose rows are auto-created per solicitation should set
  `dibbs_disposable = True` so import-batch delete treats them as non-work.

## 4. Before changing services
- **No Django ORM inside `with sync_playwright():`** — the mssql driver raises
  `SynchronousOnlyOperation` inside Playwright's loop. Scrapers return plain dicts;
  persistence happens after the browser closes.
- Award inserts: raw chunked `executemany` into `dibbs_award_staging`, then
  `usp_process_award_staging`. Never `bulk_create` awards (mssql `OUTPUT INSERTED`).
  On proc failure, `awards_file_importer._call_proc` deletes that `stage_id`'s
  staging rows before re-raising.
- `usp_process_award_staging` lives in `sql/`; deploy manually via SSMS
  (`CREATE OR ALTER PROCEDURE`) to **every** environment, bump the in-body
  `-- PROC_VERSION:` and `services/proc_versions.py` together;
  `manage.py verify_stored_procs` checks drift.
- Chunk every `__in` under SQL Server's 2,100-parameter limit (importer chunk
  sizes are tuned for it). Prefer subqueries over materialized id lists.
- DIBBS files are ISO-8859-1 (`DIBBS_FILE_ENCODING`), never UTF-8.
- `import_completed` must be fired with `send_import_completed()` (robust send),
  after lines and approved sources are written — receivers query them.
- `CompanyCAGE`: exactly one active `is_default=True` row; the CAGE views enforce it.
- `match_new_mods_after_import` emails the contract reviewer (or the
  "Contract Administrators" group) for each newly matched mod via
  `mod_notifications.notify_new_mods`. Keep that call wrapped in try/except —
  mail must never break an import. Bulk/backfill matching (`rematch_unmatched_mods`)
  must not notify, or old mods get emailed en masse.

## 5. Before changing views / templates
- `@login_required` everywhere; AW upload also checks `is_staff`.
- Full pages extend `dibbs/base.html`; pass `section` (`imports`, `settings`) where
  the sub-nav keys off it. No CDN tags (Bootstrap is in the global base).
- `import/progress.html` reads each step's JSON keys; `_save_step` merges the same
  keys into `ImportJob.step_results`. Change both together.
- `awards` result view pops session key `aw_import_result` — keep the name.
- URL names referenced outside the app: `dibbs:dibbs_notices`,
  `dibbs:competitor_watchlist`, `dibbs:acknowledge_contract_mod`,
  `dibbs:solicitation_detail`, `dibbs:dashboard`. `app_name` must stay `'dibbs'`.

## 6. Background tasks
New scheduled work: callable in `dibbs/tasks/` + `TASK_FUNCTIONS` entry in
`core/management/commands/run_background_tasks.py` + a `core.ScheduledTask` row
seeded by data migration. All three, or it silently never runs.

## 7. Migrations
- `0001_initial` replaces the 63 historical `sales` migrations. Do not edit its
  `replaces`, and never delete `sales` rows from `django_migrations`.
- No MARS in data migrations: materialize reads with `list(...values())` before writing.
- Migrations must run on SQL Server (prod/dev) and SQLite (CI).

## 8. Verify
`python manage.py check`, `python manage.py makemigrations --check`,
`python manage.py test dibbs quote intake contracts products core`.
For award changes also run `verify_stored_procs` against the target DB.

## 9. Release notes
`release_notes/YYYY-MM-DD-slug.md`, frontmatter `id` = filename stem,
`tags` exactly one type + one area (use `sales` for DIBBS/quoting changes).

## Links that open another tab
Reference lookups reuse one named tab per destination instead of `_blank`:
`statz_sam`, `statz_dla_cage`, `statz_entity`, `statz_sol_pdf`,
`statz_dibbs_data`. Do **not** add `rel="noopener"` to these -- Chrome then
opens an isolated tab it can never find by name again, and tabs pile up. Use
named targets only for trusted destinations (.gov sites, our own pages); links
to scraped or user-supplied URLs (notice links, company websites) stay
`target="_blank" rel="noopener noreferrer"`.
