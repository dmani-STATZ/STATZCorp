# Sales App Dead Code Audit
Generated: 2026-04-13

## Summary
- Total items flagged: 6
- Category A (Definitely Dead): 0
- Category B (Probably Stale): 4
- Category C (Needs Verification): 2

---

## A. Definitely Dead

| Item | Type | Location | Reason |
|------|------|----------|--------|
| *(none)* | — | — | All views have matching URL patterns; all URL patterns resolve to existing views; all form classes are imported and instantiated; no orphaned templates found. |

---

## B. Probably Stale

| Item | Type | Location | Reason |
|------|------|----------|--------|
| `parse_ca_zip()` / entire `ca_parser.py` module | Service file | `sales/services/ca_parser.py` | Zero import sites anywhere in the `sales` app (confirmed via grep — no `from sales.services.ca_parser import` or `from .ca_parser import` anywhere). `CONTEXT.md` and `DIBBS_System_Spec.md` explicitly describe it as "optional legacy/ad-hoc bulk path, not invoked by the nightly `auto_import_dibbs` WebJob." `fetch_ca_zip` was removed from `dibbs_fetch.py`. The nightly pipeline uses `parse_pdf_data_backlog()` instead. |
| `rfq_send_single` view + URL pattern `rfq/send/` | View + URL | `sales/views/rfq.py:149`, `sales/urls.py:203` | `@require_POST` view with URL name `sales:rfq_send_single`. No template, JavaScript, or other view in the entire codebase references this URL name or path. Superseded by the grouped `rfq_queue_send` / `rfq_queue_mark_sent` batch-send flow introduced with the RFQ Queue. |
| `rfq_supplier_search` view + URL pattern `rfq/supplier-search/` | View + URL | `sales/views/rfq.py:1014`, `sales/urls.py:215` | JSON supplier typeahead for an "ad-hoc RFQ panel". No template or JavaScript in the codebase references this URL or URL name. Functionality now served by `rfq_manual_supplier_search` (HTMX endpoint at `rfq/manual-supplier-search/`) which drives the workbench sidebar typeahead. |
| `supplier_search_ajax` view + URL pattern `solicitations/supplier-search/` | View + URL | `sales/views/solicitations.py:1877`, `sales/urls.py:160` | JSON supplier search documented in `CONTEXT.md` as "for decision screen." No template, JavaScript, or other view references this URL name (`sales:supplier_search_ajax`) or the path `/solicitations/supplier-search/` anywhere in the codebase. The "decision screen" UI no longer appears in any current template. |

---

## C. Needs Verification

| Item | Type | Location | Notes |
|------|------|----------|-------|
| `sol_review_legacy_redirect` (URL name `sol_review_decision`) | View + URL | `sales/views/solicitations.py:1867`, `sales/urls.py:158` | Named "legacy_redirect" in code; takes a `sol_pk` (integer) and redirects to `solicitation_workbench` by sol number. No current template uses `{% url 'sales:sol_review_decision' %}`. `CONTEXT.md` documents the path (`/solicitations/review/<sol_pk>/`) as active. May be kept for external links or old bookmarks that stored PK-based URLs. Human should confirm whether any external system or bookmark still uses this path. |
| `research_pool_list` view + URL `/solicitations/research-pool/` | View + URL | `sales/views/solicitations.py:469`, `sales/urls.py:149` | Just a redirect: copies GET params and redirects to `solicitation_list?tab=research`. No template currently uses `{% url 'sales:research_pool_list' %}` or links to `/solicitations/research-pool/`. `CONTEXT.md` documents the path as active. May be kept as a stable bookmark-able shortcut or for external nav links. Human should confirm whether any nav link, WebJob log, or external integration depends on this URL. |

---

## Management Commands (Do Not Delete — Review Only)

| Command | Documented in CONTEXT.md/AGENTS.md? | Notes |
|---------|--------------------------------------|-------|
| `auto_import_dibbs` | Yes — both | Active nightly Azure WebJob. Three-phase: Loop A (fetch missing DIBBS archive files + `run_import()`), Loop B (fetch set-aside PDFs in batches of 10), Loop C (`parse_pdf_data_backlog()` + optional LLM `SolAnalysis` when `SOL_ANALYSIS_ENABLED=True`). Do not remove. |
| `scrape_awards` | Yes — both | Active nightly Azure WebJob (`webjobs/run_scrape_awards/run.sh`). Reconciles DIBBS award dates, scrapes new records via Playwright, runs `awards_file_importer.import_aw_records()`, calls `queue_we_won_awards`, sends failure alert email. Do not remove. |
| `fetch_pending_pdfs` | Yes — both | Explicitly labeled "deprecated as a frequent scheduled WebJob" in the command's own file header and in AGENTS.md §11. `auto_import_dibbs` Loop B now handles nightly set-aside PDF harvest. Kept for manual runs and optional queue catch-up for non-set-aside sols. Review whether a cron entry still schedules this — if so, consider removing the cron while keeping the command. |
| `refresh_match_counts` | Yes — AGENTS.md §4 | Active. Queries `SolicitationMatchCount` (unmanaged view), bulk-updates `Solicitation.match_count` column. Run by nightly WebJob (`webjobs/refresh_match_counts/run.sh`) and triggerable via the Suppliers list page staff button. Do not remove. |

---

## SQL Files

| File | Referenced in CONTEXT.md/AGENTS.md? | Notes |
|------|-------------------------------------|-------|
| `sales/sql/usp_process_award_staging.sql` | Yes — AGENTS.md §8 extensively | Active stored procedure. Stages raw AW rows from `dibbs_award_staging` into `dibbs_award` / `dibbs_award_mod`. Deploy changes via SSMS with `CREATE OR ALTER PROCEDURE`. Never run via Django or management command. Protected false-positive per audit instructions. |
| `sales/sql/dibbs_supplier_nsn_scored.sql` | Yes — AGENTS.md §5, multiple sections | Active DDL for SQL Server view `dibbs_supplier_nsn_scored`. Backing store for unmanaged model `SupplierNSNScored`; used by `services/matching.py` Tier 1 matching. Deploy changes via SSMS with `CREATE OR ALTER VIEW`. Protected false-positive per audit instructions. |
| `sales/sql/dibbs_solicitation_match_counts.sql` | Yes — AGENTS.md §4 | Active DDL for SQL Server view `dibbs_solicitation_match_counts`. Queried once per run by `refresh_match_counts` command to bulk-update `Solicitation.match_count`. Deploy changes via SSMS with `CREATE OR ALTER VIEW`. Never via Django migrations or management commands. |

---

## Unmanaged Models (Listed Separately — Do Not Flag as Dead)

| Model | `db_table` | Location | Notes |
|-------|------------|----------|-------|
| `SupplierNSNScored` | `dibbs_supplier_nsn_scored` | `sales/models/suppliers.py:37` | Active. Read by `services/matching.py` Tier 1. View DDL in `sales/sql/dibbs_supplier_nsn_scored.sql`. Protected false-positive. |
| `SolicitationMatchCount` | `dibbs_solicitation_match_counts` | `sales/models/suppliers.py:58` | Active. Read by `management/commands/refresh_match_counts.py`. View DDL in `sales/sql/dibbs_solicitation_match_counts.sql`. |
| `WeWonAward` | `dibbs_we_won_awards` | `sales/models/awards.py:211` | Active. Used by `services/queue_we_won_awards.py`. View must be created manually in SSMS (see AGENTS.md §8). Protected false-positive. |
