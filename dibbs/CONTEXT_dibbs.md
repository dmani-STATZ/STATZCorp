# DIBBS Context

## 1. Purpose
The `dibbs` app owns **DIBBS-sourced data** and nothing else: the daily IN/BQ/AS
solicitation import, DIBBS award records (AW file + nightly scrape + daytime
"we won" poll), procurement history and packaging pulled from solicitation PDFs,
DIBBS homepage notices, SAM.gov CAGE lookups, competitor award intelligence, and
the STATZ CAGE reference table.

It carries **no quoting workflow** — no solicitation status pipeline, no supplier
matching, no RFQs, quotes or bids. That lives in the `quote` app, which reads
`dibbs` tables and reacts to the `import_completed` signal. `dibbs` must never
import from `quote`.

History: these models, services and pages lived in the `sales` app until
2026-09. `sales` was a never-used prototype; its DIBBS data pipeline moved here
with **tables and data untouched** and the rest of `sales` was deleted. The old
spec is archived at `docs/legacy/sales_DIBBS_System_Spec.md`.

## 2. App Identity
- **Django app name / label:** `dibbs` — `DibbsConfig` (`dibbs/apps.py`)
- **URL prefix:** `/dibbs/`, namespace `dibbs:`. `/sales/<path>` redirects to `/dibbs/<path>`
  (root `STATZWeb/urls.py`) so old bookmarks to surviving pages keep working.
- **Shell template:** `templates/dibbs/base.html` (sub-nav: Dashboard, Imports, Awards,
  Wins, Competitors, Notices, CAGE Settings).

## 3. Key Files
| File | Responsibility |
|---|---|
| `models/solicitations.py` | `ImportBatch` (`tbl_ImportBatch`), `ImportJob` (`tbl_ImportJob`), `Solicitation` (`dibbs_solicitation`), `SolicitationLine` (`dibbs_solicitation_line`, incl. `bq_raw_columns` 121-cell BQ row), `NsnProcurementHistory` |
| `models/approved_sources.py` | `ApprovedSource` (`tbl_ApprovedSource`) — AS file rows; the same (NSN, CAGE, P/N) repeats once per daily batch |
| `models/awards.py` | `AwardImportBatch`, `DibbsAward`, `DibbsAwardMod`, `DibbsAwardStaging(+Error)`, unmanaged `WeWonAward` (view `dibbs_we_won_awards`) |
| `models/cages.py` | `CompanyCAGE` (`dibbs_company_cage`) — STATZ's own CAGEs + BQ header defaults |
| `models/packaging.py`, `sol_analysis.py` | `SolPackaging` (Section D), `SolAnalysis` (LLM-extracted PDF requirements) |
| `models/sam_cache.py` | `SAMEntityCache` — 30-day SAM.gov CAGE cache |
| `models/dibbs_notices.py` | `DibbsNotice` (`dibbs_notice`) |
| `models/competitor_*.py` | `CompetitorWatchlist`, `CompetitorAwardParseStatus`, `CompetitorAwardEntity` (`dibbs_competitor_*`) |
| `services/importer.py` | IN/BQ/AS persistence (`parse_dibbs_files`, `create_import_batch`, `upsert_solicitations`, `upsert_lines_and_sources`, `run_import`, `purge_expired_pdf_blobs`) |
| `services/parser.py` | Pure IN/BQ/AS file parser |
| `services/dibbs_fetch.py`, `dibbs_session.py`, `dibbs_pdf.py`, `ca_parser.py` | DIBBS downloads (Playwright + requests), PDF fetch/parse, CA zip procurement history |
| `services/awards_file_importer.py`, `awards_file_parser.py`, `awdrecs_parser.py`, `dibbs_awards_scraper.py`, `poll_we_won_today.py` | Award ingestion — all paths stage rows and call `usp_process_award_staging` |
| `services/contract_mods.py` | DIBBS mod ↔ `contracts.Contract` matching; `mods_for_contract` used by contracts |
| `services/competitor_stats.py`, `competitor_supplier_intel.py` | Competitors Numbers aggregation (canonical) + award-PDF entity extraction |
| `services/sam_entity.py`, `cage_utils.py`, `dibbs_notices.py`, `sol_analysis.py`, `staging_cleanup.py`, `proc_versions.py`, `proc_verification.py` | Supporting services |
| `signals.py` | `import_completed` signal + `send_import_completed(batch)` |
| `db_objects.py` | Non-Django DB objects: SQLite `dibbs_we_won_awards` shim, SQL Server `DF_dibbs_award*` URL defaults, filtered competitor index |
| `sql/usp_process_award_staging.sql` | Award staging stored procedure (deployed manually via SSMS) |
| `context_processors.py` | `dibbs_notice_count` (global header badge) |
| `views/` | dashboard, imports, read-only solicitation detail + PDF, awards, wins, contract-mod acknowledge, notices, competitors, entity lookup, CAGE settings |

## 4. Data Model Notes
- Every table keeps the name it had under `sales`, except four renamed in `0003`:
  `sales_dibbsnotice → dibbs_notice`, `sales_competitor_* → dibbs_competitor_*`.
- `Solicitation.status` is **legacy and frozen**: nothing sets it (new rows default
  `'New'`). It survives only because `usp_process_award_staging` filters
  `status <> 'NO_BID'`. Workflow state is `quote.QuoteSolicitation`.
- `NsnProcurementHistory.nsn` is the 13-digit form; `SolicitationLine.nsn` keeps
  DIBBS's hyphenated form; `ApprovedSource.nsn` is 13-digit. Query both forms.
- `DibbsAward` has no quantity and no unit price.

## 5. Flows
**Daily import (interactive):** `/dibbs/import/` upload or "fetch from DIBBS" →
`ImportJob` → progress page drives 3 AJAX steps: parse (+ PDF blob retention purge)
→ solicitations → lines & approved sources (+ temp-file cleanup + `import_completed`).

**Daily import (WebJob):** `manage.py auto_import_dibbs` — Loop A imports missing
dates via `run_import()` (fires `import_completed`), purges expired PDF blobs, then
harvests CA zips for open set-aside solicitations and parses procurement history /
packaging inline. Zero-record dates get an empty `ImportBatch`
(`imported_by='auto_import_dibbs:empty'`).

**Awards:** nightly `manage.py scrape_awards` (inventory → sync dates as
`AwardImportBatch(scrape_status=MISSING)` → one Playwright session per date,
oldest non-SUCCESS first, per-page save, 3-failure circuit breaker, today never
queued); daytime `poll_we_won_today` background task; manual AW upload at
`/dibbs/awards/import/` (staff only). All stage via raw `executemany` into
`dibbs_award_staging` and call `usp_process_award_staging`.

**Batch delete:** `/dibbs/import/batch/<id>/delete/` removes the batch's approved
sources and every solicitation nothing else points at. Relations from models with
`dibbs_disposable = True` (quote's auto-seeded state + matches) don't count as work.

## 6. Signals (the only cross-app hook)
`dibbs.signals.import_completed(sender=ImportBatch, batch=...)` fires once per
imported batch, via `send_robust` — a failing receiver is logged, never raised,
so downstream bugs cannot fail an import. `quote` listens to seed workflow state
and run supplier matching.

## 7. Background Work
- WebJobs: `run_auto_import_dibbs` (`auto_import_dibbs`), `run_scrape_awards`
  (`scrape_awards`), optional `run_fetch_pending_pdfs` (`fetch_pending_pdfs`).
- `run_background_tasks` (core) tasks owned here: `poll_we_won_today`,
  `check_dibbs_notices` (`dibbs/tasks/`).
- Env vars: `AWARDS_ALERT_EMAIL`, `GRAPH_MAIL_*` (alert mail), `SAM_API_KEY`.

## 8. Cross-App Dependencies
- **Reads:** `contracts` (`Company` for `CompanyCAGE.company`, `Contract` for mod
  matching, `normalize_contract_number`), `intake` (`_extract_pdf_texts` in
  competitor intel), `core` (`ScheduledTask`, Anthropic client).
- **Used by:** `quote` (models + signal), `intake` (`DibbsAward`, `AwardImportBatch`,
  `WeWonAward`, `CompanyCAGE`, `dibbs_session`), `contracts` (`contract_mods`,
  `dibbs:acknowledge_contract_mod`, `dibbs:competitor_watchlist`), `products`
  (NSN pages read solicitations, approved sources, procurement history, awards),
  `core` (global search, task registry), global templates (notices badge,
  Competitors link, "DIBBS Data" sidebar).

## 9. Permissions
`@login_required` on every view. AWARD file upload requires `is_staff`.
`AppRegistry`: `dibbs/0002` copies any `sales` registry row + grants to `dibbs`;
with no row the app is fail-open (same as `sales` was).

## 10. Migrations
- `0001_initial` — baseline. `replaces` all 63 historical `sales` migrations, so
  on existing databases it is recorded as applied without running. On a fresh DB
  it creates the tables plus `db_objects` (URL defaults, competitor index, SQLite
  view) and seeds the `check_dibbs_notices` task. **Never edit `replaces` and never
  delete `sales` rows from `django_migrations`.**
- `0002_drop_sales_workflow_tables` — one-way: drops the old workflow tables and
  views, relabels content types `sales → dibbs`, copies AppRegistry, deletes the
  `send_queued_rfqs` task row.
- `0003_drop_sales_workflow_columns` — drops `bucket`, `bucket_assigned_by`,
  `hubzone_requested_by`, `match_count`, review-claim and research-flag columns
  from `dibbs_solicitation`; renames the four legacy tables.

## 11. Known Gaps
1. `Solicitation.status` should be dropped once `usp_process_award_staging` stops
   referencing it (proc change → bump `PROC_VERSION` → deploy via SSMS everywhere).
2. The whole downloaded `bq` file is not retained — only each line's 121-cell row.
3. `SolicitationLine` has no unique constraint on `(solicitation, nsn)` although
   the importer diffs on it.
4. `item_description_indicator`, `trade_agreements_indicator`,
   `buy_american_indicator`, `higher_level_quality_indicator` on
   `SolicitationLine` are never populated; the values sit in `bq_raw_columns`.
