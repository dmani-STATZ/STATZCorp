# Dead Code Forensic Audit — STATZWeb (STATZCorp)

**Date:** 2026-07-09
**Scope:** Read-only forensic audit of the entire Django monolith. Non-destructive — this report is the only file created. Nothing else was modified, deleted, refactored, or reformatted.
**Method:** Reachability model built from `STATZWeb/settings.py` (`INSTALLED_APPS`, `MIDDLEWARE`, `TEMPLATES` context processors), `STATZWeb/urls.py` include graph, and `core/management/commands/run_background_tasks.py` (`TASK_FUNCTIONS`). Repo-wide search for every flagged symbol/template/URL, accounting for Django auto-discovery, lazy in-method imports, string-built template/URL paths, JS `fetch()` hardcoded paths, WebJob task registration, and vendored (no-CDN) assets.

> **PRIME DIRECTIVE:** This is an audit, not a cleanup. Every item below is a *candidate* with evidence. Deletion is a separate, human-approved follow-up that will consume this report as input. In a Django monolith, "no static reference" does **not** prove "dead" — tiering reflects that.

---

## 1. Executive Summary

### Apps covered (all of `INSTALLED_APPS`)
`STATZWeb`, `users`, `inventory`, `imports`, `contracts`, `sales`, `accesslog`, `mailer`, `processing`, `intake`, `training`, `reports`, `suppliers`, `products`, `tools`, `transactions`, `core`. (`crispy_forms`, `crispy_bootstrap5`, `corsheaders`, `django_extensions`, `django_browser_reload`, and `django.contrib.*` are third-party and out of scope.)

### Counts per tier per category

| Category | Tier A (safe candidate) | Tier B (confirm) | Tier C (keep/aware) |
|---|---:|---:|---:|
| Orphaned Python modules | 4 | 2 | — |
| Dead view callables | 1 | 7 | — |
| Orphaned URL names | 8 | 6 | 13 |
| Unused templates | 11 | 2 | 1 |
| Dead static assets | 5 | 3 | (vendored skipped) |
| Unused models | 0 | 0 | — |
| Dead forms | 2 | 4 | — |
| Dead template tags / signals / context procs / mgmt cmds | 0 | 1 | (all mgmt cmds = C) |
| Unreachable / legacy code | 2 | 3 | 2 |
| **Totals** | **33** | **28** | **~29 + all migrations/vendored** |

### Headline Processing verdict

> **Processing is approximately 10–15% superseded at the *code* level.** Only the shadowed `processing/views.py` module and ~4 unrouted view functions have in-app or intake equivalents and carry no runtime references. **The remaining ~85–90% of the `processing` app is load-bearing and MUST NOT be removed**, because intake did **not** replace processing — it added a *parallel* draft→finalize workflow. The nightly DIBBS scrape still injects into the Processing queue (`queue_we_won_awards`) immediately before it injects intake drafts (`queue_we_won_drafts`), and `contracts`/`sales` still import processing's `SequenceNumber`, `contract_utils`, `pdf_parser`, and staging models.

### No `unused models` were found
Every model in every app has inbound FK/M2M, an admin registration, a query, or a form/serializer use. Unmanaged SQL-view-backed models (`sales.SupplierNSNScored`, `sales.SolicitationMatchCount`, `sales.WeWonAward`) are LIVE and protected. Per MSSQL guidance, no model was advanced past code-analysis anyway — any future model removal must first verify the SQL Server table is empty.

---

## 2. Per-Category Findings

### 2.1 Orphaned Python modules

| Path | Symbol | References found (path:line or "none — searched: …") | Dynamic-use risk | Tier | Recommended action |
|---|---|---|---|---|---|
| `processing/views.py` | module (`process_contract_form` re-export) | Shadowed by package `processing/views/` — verified at runtime: `processing.views.__file__` → `processing/views/__init__.py`. Searched: `import processing.views`, `from processing.views import` (all resolve to the package). No unique symbol depends on the module file. | None — file is unimportable | **A** | Delete module file (package supersedes it) |
| `sales/views.py` | module (`DashboardView` CBV) | Shadowed by package `sales/views/`; verified `sales.views.__file__` → `sales/views/__init__.py`. `DashboardView` referenced only at `sales/views.py:6` (def). `sales:dashboard` routes to `dashboard` from `sales/views/dashboard.py`. Searched: `DashboardView`, `from sales.views import`. | None — file is unimportable | **A** | Delete module file |
| `contracts/managers.py` | `ActiveUserManager` (+ `User.active_objects = …`) | none — searched: `contracts.managers`, `from contracts import managers`, `from .managers`, `ActiveUserManager`, `active_objects`. Module never imported; `active_users_processor` uses `User.objects` directly. | Low | **A** | Delete after confirming no runtime monkey-patch reliance |
| `users/sql_fix.py` | `create_app_registry_table` | none — searched: `sql_fix`, `from users.sql_fix`, `import users.sql_fix`, `create_app_registry_table`. Only a `if __name__=="__main__"` self-run. | Low (one-off SQL repair script) | **A** | Delete (one-shot repair, never wired) |
| `suppliers/utils.py` | `scrape_supplier_site` | none — searched: `suppliers.utils`, `from suppliers import utils`, `from .utils`, `scrape_supplier_site`. `suppliers/AGENTS_suppliers.md` explicitly documents it as unwired. | Medium — "scrape" helper may be intended for enrichment | **B** | Confirm enrichment pipeline doesn't plan to use it; then delete |
| `STATZWeb/pdf_security.py` | `get_pdf_security_settings` | none — searched: `pdf_security`, `from STATZWeb.pdf_security`, `get_pdf_security_settings`. Note `settings.py` defines `PDF_MAX_PAGES`/`PDF_MAX_FILE_SIZE` directly. | Medium — PDF upload hardening is security-sensitive; may have been intended to gate uploads and never wired | **B** | Confirm PDF upload validators don't need it before removing |

### 2.2 Dead view callables (defined but unrouted / unused as base class)

| App | Symbol | Definition | References found | Dynamic-use risk | Tier | Recommended action |
|---|---|---|---|---|---|---|
| sales | `DashboardView` (CBV) | `sales/views.py:6` | Inside shadowed module only (see 2.1). `sales:dashboard` uses `sales/views/dashboard.py:dashboard`. | None | **A** | Removed with `sales/views.py` |
| processing | `process_contract_form` (fn) | `processing/views/processing_views.py:1140` | Not in `processing/urls.py`; only `processing/views/__init__.py` + shadowed `views.py` re-export. Superseded by `ProcessContractUpdateView` (renders same template). | Low (re-exported) | **B** | Confirm no external import of `processing.views.process_contract_form`; then remove fn |
| processing | `process_contract` (fn) | `processing/views/processing_views.py:1870` | Not routed — `process/<id>/` uses a `lambda` redirect. Only `__init__.py` re-export. | Low | **B** | Confirm; then remove |
| processing | `initiate_processing` (fn) | `processing/views/processing_views.py:1825` | Imported in `processing/urls.py:33` but **not** in any `urlpatterns`; no `initiate_processing(` caller. Lock logic inlined in `start_processing`. | Low | **B** | Confirm; then remove fn + unused import |
| processing | `validate_contract_number` (fn) | `processing/views/processing_views.py:2669` | Not imported in `urls.py`; no route; no caller found. | Low | **B** | Confirm; then remove |
| users | `save_user_setting` (fn) | `users/views.py:487` | Not in `users/urls.py`; live AJAX endpoint is `users:settings-save` (`ajax_save_setting`). Only stale `users/CONTEXT_users.md` mention. | Low | **B** | Confirm; then remove |
| users | `manage_settings` (fn) | `users/views.py:522` | Not in `users/urls.py`; live is `users:settings-view` (`user_settings_view`). | Low | **B** | Confirm; then remove |
| contracts | `get_acknowledgment_letter` (fn) | `contracts/views/acknowledgment_views.py:276` | **Routed** at `contracts/urls.py:836` but no template/JS caller. Superseded by `acknowledgment_letter_page`. | Medium (still routable by direct URL) | **B** | Confirm no bookmark/external dependency; then remove view + URL |

### 2.3 Orphaned URL names

**Tier A — sales legacy RFQ / superseded endpoints (confirmed by this pass + prior `sales/DEAD_CODE_AUDIT.md`):**

| URL name | Definition | References found | Tier | Action |
|---|---|---|---|---|
| `sales:rfq_send_single` | `sales/urls.py:205` → `views/rfq.py:151` | none — searched `sales:rfq_send_single`, `rfq/send/`, `{% url %}`, `reverse(`. Doc example only in `DIBBS_System_Spec.md`. | **A** | Remove URL + view (superseded by queue batch-send) |
| `sales:rfq_supplier_search` | `sales/urls.py:217` → `views/rfq.py:1016` | none — searched name + `rfq/supplier-search/`. Superseded by `rfq_manual_supplier_search`. | **A** | Remove URL + view |
| `sales:supplier_search_ajax` | `sales/urls.py:162` → `views/solicitations.py:1877` | none — searched name + `solicitations/supplier-search/`. | **A** | Remove URL + view |
| `sales:rfq_send_to_approved_source` | `sales/urls.py:215` → `views/rfq.py:854` | none — searched name + `rfq/send-to-approved-source/`. Docstring only. | **A** | Remove URL + view |
| `sales:rfq_send_to_adhoc` | `sales/urls.py:216` → `views/rfq.py:926` | none — searched name + `rfq/send-to-adhoc/`. | **A** | Remove URL + view |
| `sales:rfq_send_to_existing` | `sales/urls.py:218` → `views/rfq.py:1065` | none — searched name + `rfq/send-to-existing/`. | **A** | Remove URL + view |
| `sales:quote_select_for_bid` | `sales/urls.py:213` → `views/rfq.py:1116` | none — searched name + `select-for-bid`. Docs only. | **A** | Remove URL + view |
| `sales:rfq_cage_preview` | `sales/urls.py:214` → `views/rfq.py:745` | none — searched name + `rfq/cage-preview/`. | **A** | Remove URL + view |

**Tier B — diagnostics / demo / superseded contracts routes (manual-access plausible):**

| URL name | Definition | References found | Tier | Action |
|---|---|---|---|---|
| `contracts:contract_workspace_demo` | `contracts/urls.py:287` (`demo.html` TemplateView) | none — searched name + `contracts/demo`. | **B** | Confirm demo not needed; then remove |
| `contracts:get_acknowledgment_letter` | `contracts/urls.py:836` | none — searched name + `{% url %}`/`reverse(`. Superseded by `acknowledgment-letter-page`. | **B** | See 2.2 |
| `contracts:create_reminder` | `contracts/urls.py:513` | none — links use `contracts:add_reminder`. (POST field `create_reminder` is unrelated.) | **B** | Confirm; then remove |
| `contracts:test_app_name` | `contracts/urls.py:615` | none — diagnostic. | **B** | Confirm diagnostic obsolete; then remove |
| `users:test_app_name` / `users:debug_permissions` / `users:debug_auth_config` / `users:check_auth_method` | `users/urls.py:27/28/62/50` | none in code — middleware/permission diagnostics hit by manually typed URL; documented in `users/CONTEXT_users.md`. | **B** | Keep if diagnostics still wanted; else remove views+URLs |

**Tier C — LOW-keep (referenced by hardcoded path, infra, OAuth, or bookmark — do NOT delete):**

| URL name | Why keep |
|---|---|
| `manifest`, `service_worker` | Hardcoded `/manifest.json`, `/sw.js` in `base_template.html` + middleware allow-list |
| `cert_error`, `download_cert`, `api_health_check` | Hardcoded paths in `static/js/cert-checker.js` / `cert_error.html` |
| `health_check`, `azure_health` | Azure health probes; hit by path in `core/tests.py` |
| `system_test`, `system_test_api` | Path listed in `STATZWeb/middleware.py` public URLs |
| `microsoft_login`, `microsoft_callback` (root, non-namespaced) | OAuth redirect targets; Azure app registration may require root paths |
| `sales:sol_review_decision`, `sales:research_pool_list` | PK-based bookmark / `?tab=research` shortcut redirects (per prior sales audit) |

### 2.4 Unused templates

| Path | References found | Dynamic-use risk | Tier | Action |
|---|---|---|---|---|
| `templates/add_announcement.html` | none — `STATZWeb/views.py:add_announcement` returns `JsonResponse` only; template extends non-existent `base.html`. | None | **A** | Delete |
| `templates/delete_announcement.html` | none — `delete_announcement` returns `JsonResponse` only. | None | **A** | Delete |
| `templates/contracts/includes/contract_search_results.html` | none — project-level stale duplicate; live copy `contracts/templates/contracts/includes/contract_search_results.html` rendered by `folder_tracking_views.py:186`. | None | **A** | Delete project-level dup |
| `templates/suppliers/includes/status_toggle.html` | none — searched `status_toggle`; `supplier_edit.html` uses `toggle_switch.html`. Doc-only in `docs/template_tracking.md`. | Low | **A** | Delete |
| `contracts/templates/contracts/partials/contract_splits.html` | none — comment-only stub; split UI in `clin_detail.html` + `contract_splits.js`. | None | **A** | Delete (+ its README) |
| `contracts/templates/contracts/includes/log_payment_modal.html` | none — Finance Audit "Slice 2C" retired Log Payment; zero `{% include %}`. Pairs with dead `log_payment_modal.js`. | Low | **A** | Delete (batch with JS) |
| `contracts/templates/contracts/dfas_contract_matcher_modal.html` | none — `dfas_import_review.html` uses inline modals + `dfas_import_review.js`. | Low | **A** | Delete |
| `training/templates/training/manage_matrix_success.html` | none — `manage_matrix` renders `manage_matrix.html` then redirects. | None | **A** | Delete |
| `reports/templates/reports/admin_dashboard.html` | none — no view/URL renders it; references dead URL names; pre-`0002_rebuild` legacy. | Low | **A** | Delete |
| `reports/templates/reports/user_dashboard.html` | none — replaced by `hub.html`; references dead URLs. | Low | **A** | Delete |
| `reports/templates/reports/request_form.html` | none — `request_form` is a context var for inline form in `hub.html`, not this file. | Low | **A** | Delete |
| `sales/templates/sales/rfq/pending.html` | `rfq_pending` view **redirects only** to `sales:rfq_queue` (retired), BUT `sales/AGENTS_sales.md` still documents this file as live (Matches tab). Conflict. | Medium | **B** | Human confirm retirement; couples with `mailto_buttons.html` + `sales:rfq_mailto` |
| `sales/templates/sales/rfq/partials/mailto_buttons.html` | Only included from `pending.html` (+ self-recursion). `sales/AGENTS_sales.md` says detail Matches tab does not include it. | Medium | **B** | Confirm with `pending.html` cluster |
| `inventory/templates/inventory/delete_form.html` | none — `inventory/AGENTS_inventory.md`+`CONTEXT_<app>.md` say "orphaned, no view renders it"; delete is AJAX. | Low | **A** | Delete |
| `_extra/VISUAL_TEST.html` | Dev artifact outside template dirs (`_extra/`). | — | **C** | Keep (out-of-run by policy) |

> **Inverse note (not deletion candidates — missing templates referenced by live views):** `contracts/clin_acknowledgment_form.html` (`clin_views.py:195`), `contracts/contacts/contact_confirm_delete.html` (`contacts_views.py:159`), `contracts/contacts/address_confirm_delete.html` (`contacts_views.py:320`) are referenced but absent. These are latent runtime bugs, not dead code — flagged for awareness only.

### 2.5 Dead static assets (first-party only)

| Path | References found | Dynamic-use risk | Tier | Action |
|---|---|---|---|---|
| `contracts/static/contracts/js/log_payment_modal.js` | none — searched `log_payment_modal.js`, `logPaymentModal`. Slice 2C retired. Pairs with dead template. | Low | **A** | Delete (batch with template) |
| `contracts/static/js/supplier_modal.js` | none — live loads use `processing/js/supplier_modal.js`; `clin_form.html`/`idiq_processing_edit.html` define `openSupplierModal` inline. Odd path `static/js/` (not `static/contracts/js/`). | Low | **A** | Delete |
| `static/inventory/morth.css` | none — Bootswatch theme dump; self-ref only; dashboard uses global CSS chain. | None | **A** | Delete |
| `static/inventory/sandstone.css` | none — Bootswatch theme dump; self-ref only. | None | **A** | Delete |
| `contracts/static/css/components.css` | none — **empty deprecated stub**; live file is `contracts/static/contracts/css/components.css`. | None | **A** | Delete stub |
| `static/suppliers/js/supplier_enrich.js` | none as active — `supplier_detail.html` `#enrich-from-website-btn` is an `<a>` (JS early-returns for `A`); `supplier_enrich.html` uses inline `<script>`. Docs still call it bundled. | Medium | **B** | Confirm enrichment UI doesn't load it; then delete |
| `static/js/portal_dashboard.js` | none — API `users:portal_dashboard_data` is live, but no template defines required DOM ids (`portal-context-data`, `workCalendar`). | Medium | **B** | Confirm portal HTML not planned; then delete |
| `static/js/cert-checker.js` | none — `/api/health-check/` live; `.cursor/plans/…` references it; no template `<script>` include; required DOM ids only inside the file. | Medium | **B** | Confirm no cert page loads it; couples with `ssl_tags.is_cert_untrusted` |

> **Protected / vendored (skipped, never flag):** `static/admin/**`, `static/django-browser-reload/**`, `static/js/vendor/**` (chart.js, adapters), `static/css/spacelab.min.css`, the three global CSS (`theme-vars.css`, `app-core.css`, `utilities.css`), `static/sw.js` + `templates/sw.js`, `manifest.json`, favicon/icons/splash, videos, certificates, `static/admin/js/app_permissions.js` (loaded via `users/admin.py` `Media`). No `.zip` exists under `static/` (the `PROJECT_STRUCTURE`/CSS-doc reference to `static/css/css.zip` is stale).

### 2.6 Unused models

**None.** All models have inbound references, admin registration, queries, or form use. Unmanaged view-backed models (`SupplierNSNScored`, `SolicitationMatchCount`, `WeWonAward`) are LIVE (Tier C). Per MSSQL rule, no model is a deletion candidate without first confirming the backing SQL Server table is empty — not performed (read-only audit).

### 2.7 Dead forms

| Path | Symbol | References found | Tier | Action |
|---|---|---|---|---|
| `users/forms.py:65` | `AnnouncementForm` | none — never imported. `Announcement` model used in views but this form class isn't. | **A** | Delete form class |
| `processing/forms.py:89` | `ProcessClinSplitForm` | none — split persistence uses `persist_clin_splits_for_contract()` POST keys, not this form. | **A** | Delete form class |
| `contracts/forms.py:744` | `FolderTrackingForm` | Imported unused at `folder_tracking_views.py:9`; never instantiated. | **B** | Confirm; remove class + import |
| `contracts/forms.py:752` | `IdiqContractForm` | none in code — only docs. A live contracts IDIQ edit page exists (`idiq_contract_edit.html`); confirm it doesn't build this form before removing. | **B** | Human confirm IDIQ edit flow |
| `contracts/forms.py:789` | `IdiqContractDetailsForm` | none in code — only docs. | **B** | Human confirm IDIQ edit flow |
| `users/forms.py:58` | `UserRegisterForm` | Imported at `users/views.py:7` but `register()` (`:351`) redirects to Microsoft auth without instantiating. | **B** | Confirm register flow permanently OAuth-only; then remove |
| `training/forms.py:108` | `MatrixManagementForm` | Imported at `training/views.py:21` but never instantiated; `MatrixForm` used via admin. | **B** | Confirm; remove class + import |

### 2.8 Dead template tags / signals / context processors / management commands

- **Template tags:** `users/templatetags/ssl_tags.py:28` `is_cert_untrusted` — no template `{% load ssl_tags %}` usage; only referenced from the (dead) `cert-checker.js`. **Tier B** (couples with cert-checker cluster).
- **Context processors:** all registered processors in `settings.TEMPLATES` are LIVE (`contracts.reminders_processor`, `active_users_processor`, `users.*`, `STATZWeb.version_context`, `cache_version_context`, `sales.rfq_counts`, `sales.solicitation_nav_tools`, `core.api_budget`). None dead.
- **Signals:** `contracts/signals.py` is an empty stub but is imported by `contracts/apps.py:10` `ready()` — **Tier C keep** (removing it breaks the import). `transactions/signals.py`, `users/signals.py` are LIVE.
- **Management commands:** all are **Tier C** (invoked by string name from shell/WebJobs, invisible to static analysis). Review-only observations: `contracts/refresh_nsn_view` (help text marks it deprecated — NSN view auto-refreshes), `sales/fetch_pending_pdfs` (header marks deprecated as default WebJob; kept for manual catch-up), and one-off `users/` repair/diagnostic commands (`fix_appregistry`, `fix_apppermissions`, `cleanup_permissions`, `cleanup_app_permissions`, `migrate_notes`, `check_contract_table`, `check_clin_tables`, `get_content_types`). Do **not** delete without operational confirmation.

### 2.9 Unreachable / legacy code

| Path | Symbol | Evidence | Tier | Action |
|---|---|---|---|---|
| `contracts/views/contract_views.py:777-784` | commented-out `ContractLifecycleDashboardView` | Active class lives in `dashboard_views.py:162`. Dead comment block. | **A** | Delete comment block |
| `sales/services/parser.py:579` | `assign_triage_bucket` | Marked DEPRECATED (~:598); only definition + a commented call in `importer.py:153`. Bucket now set via `triage_by_sol` dict. | **B** | Confirm; then remove |
| `contracts/utils/contracts_schema.py:47,224` | `generate_contracts_schema_description`, `generate_condensed_contracts_schema` | Only definitions + `reports/docs/design.md`. Live sibling `generate_db_schema_snapshot` used by `reports/views.py:16`. | **B** | Confirm reports AI flow uses only the snapshot; then remove |
| `_extra/temp_contract_log_views.py`, `_extra/tmp_*`, `_extra/dev_commands.py`, `_extra/setup_dev.py`, etc. | scratch | Under `_extra/` (out-of-run by policy). | **C** | Keep |
| `scratch/test_stage_1.py`, `_tmp_render_check.py` (repo root) | throwaway scripts | `_tmp_render_check.py` = one-off render verification (imports live code, never imported); `scratch/test_stage_1.py` imports `processing.models` for ad-hoc testing. Not wired to anything. | **C** | Keep/aware (dev scratch); low value, safe to remove if desired but not run-path code |
| `contracts/migrations/remove_old_payment_history.py` | unnumbered migration | Historical migration artifact. | **C** | Never flag migrations (per policy) |

> **`if False:` blocks:** none found (repo-wide search returned zero).

---

## 3. Processing → Intake Superseded-Surface Ledger (Phase 2 — Headline)

Verdicts: **LIVE** (runtime-referenced), **SUPERSEDED-BUT-STILL-REFERENCED** (intake equivalent exists but processing code is still wired), **ORPHAN-CANDIDATE** (intake/in-app equivalent + no runtime reference).

| Processing symbol / file / URL | Intake counterpart (if any) | Verdict | Proof (path:line or searches) |
|---|---|---|---|
| `processing.SequenceNumber` (`processing/models.py:166`) | `intake/services/po_sequence.py` mints PO numbers against the **same** `processing_sequencenumber` table via raw T-SQL | **LIVE** | Read by `contracts` for PO/TAB defaults (`contracts/CONTEXT_contracts.md:240,246`); advanced in `finalize_and_email_contract`. Intake reuses the same table, does not replace it. |
| `processing.services.contract_utils` (`normalize_nsn`, `detect_contract_type`, `normalize_contract_number`) | intake has its own `pdf_parser` helpers | **LIVE** | `contracts/views/api_views.py:10` (`normalize_nsn`); `sales/services/queue_we_won_awards.py:16` (`detect_contract_type`) |
| `processing.services.pdf_parser` (`parse_award_pdf`, `ingest_parsed_award`) | `intake/pdf_parser.py` (separate implementation) | **LIVE** | Root `PROJECT_AGENTS.md §9` mandates keeping it; called by `upload_award_pdf` / `parse_award_pdf_from_sharepoint` in `processing_views.py` |
| `processing.models` `QueueContract`/`QueueClin` | `intake.DraftContract` (JSON-backed) | **SUPERSEDED-BUT-STILL-REFERENCED** | Still written nightly by `queue_we_won_awards`; imported by `contracts/views/company_views.py:11` and `sales/services/queue_we_won_awards.py:131` |
| `sales.services.queue_we_won_awards.queue_we_won_awards` (Processing-queue injection) | `intake.services.queue_we_won_drafts.queue_we_won_drafts` (draft injection) | **SUPERSEDED-BUT-STILL-REFERENCED (parallel)** | **Both** run: `scrape_awards.py:465` then `:481`; `poll_we_won_today.py:167` then `:179`. Processing injection is NOT retired. |
| `processing` queue/edit/finalize UI (`/processing/…`, `contract_queue.html`, `process_contract_form.html`, `idiq_processing_edit.html`, modals) | intake `draft_queue.html` / `draft_edit.html` | **SUPERSEDED-BUT-STILL-REFERENCED** | `STATZWeb/urls.py:135` routes `/processing/`; templates use `processing:` URLs internally; app surfaced via DB `AppRegistry`. Fed by the live queue injection above. |
| `processing.forms.ProcessContractForm` / `ProcessClinForm` | intake schemas (`intake/schemas.py`) | **LIVE** | Canonical contract header create/edit form (`contracts` docs point here); used by `ProcessContractUpdateView` |
| `processing/models.py` `ProcessContract/ProcessClin/ProcessClinSplit/ProcessContractCharge` | intake draft JSON | **SUPERSEDED-BUT-STILL-REFERENCED** | Materialized to `contracts.*` in `finalize_and_email_contract`; still reachable via processing UI |
| `processing.finalize_contract` / `finalize_and_email_contract` / `finalize_idiq_contract` | `intake/finalize.py` | **SUPERSEDED-BUT-STILL-REFERENCED** | Routed in `processing/urls.py:75-76,127`; the only write path from processing → contracts |
| `processing/email_compose.html` + `email_compose_page`/`send_contract_email` | `intake/email_compose.html` | **SUPERSEDED-BUT-STILL-REFERENCED** | Routed at `processing/urls.py:77-78` |
| `processing/views.py` (module file) | package `processing/views/` | **ORPHAN-CANDIDATE** | Shadowed by package; `processing.views.__file__` resolves to `views/__init__.py`. No unique dependent. (Tier A) |
| `processing_views.process_contract_form` (fn) | `ProcessContractUpdateView` (same app) | **ORPHAN-CANDIDATE** | Unrouted; searched `processing/urls.py` — no route; only `__init__.py` re-export (Tier B) |
| `processing_views.process_contract` (fn) | `process/<id>/` lambda redirect | **ORPHAN-CANDIDATE** | Unrouted (Tier B) |
| `processing_views.initiate_processing` (fn) | `start_processing` (same app) | **ORPHAN-CANDIDATE** | Imported in `urls.py:33` but not in `urlpatterns`; no caller (Tier B) |
| `processing_views.validate_contract_number` (fn) | — | **ORPHAN-CANDIDATE** | Unrouted; no caller (Tier B) |
| `processing/forms.py:89` `ProcessClinSplitForm` | — | **ORPHAN-CANDIDATE** | Never imported; split persistence via POST keys (Tier A) |

**Verdict sentence:**

> **Processing is approximately 10–15% superseded (code-level).** The load-bearing surfaces that **MUST NOT be removed** are: `SequenceNumber` (and its table, shared with intake), `services/contract_utils`, `services/pdf_parser`, the `QueueContract`/`QueueClin`/`ProcessContract`/`ProcessClin`/`ProcessClinSplit`/`ProcessContractCharge` models, the entire `/processing/` UI and finalization flow, `ProcessContractForm`/`ProcessClinForm`, and the `queue_we_won_awards` nightly injection path. Intake adds a *parallel* workflow; it has **not** decommissioned any processing surface. Do **not** delete or move the `processing` app.

---

## 4. Proposed Deletion Batches (plan only — each a future standalone prompt)

Each batch is independently testable. Tier A items only. Ordered low-risk → higher-touch.

- **Batch 1 — Shadowed view modules (2 files).** Delete `processing/views.py` and `sales/views.py`. Verify: `python manage.py check`, load `/processing/queue/` and `/sales/`. Zero functional impact (packages already win).
- **Batch 2 — Inventory Bootswatch dumps + empty CSS stub (3 files).** Delete `static/inventory/morth.css`, `static/inventory/sandstone.css`, `contracts/static/css/components.css`. Verify: `collectstatic` + inventory dashboard render.
- **Batch 3 — Finance Audit "Slice 2C" leftovers (2 files).** Delete `contracts/static/contracts/js/log_payment_modal.js` + `contracts/templates/contracts/includes/log_payment_modal.html`. Verify: Finance Audit page renders, no console error.
- **Batch 4 — Superseded/duplicate templates (8 files).** `templates/add_announcement.html`, `templates/delete_announcement.html`, `templates/contracts/includes/contract_search_results.html` (project-level dup), `templates/suppliers/includes/status_toggle.html`, `contracts/templates/contracts/partials/contract_splits.html` (+ README), `contracts/templates/contracts/dfas_contract_matcher_modal.html`, `training/templates/training/manage_matrix_success.html`, `inventory/templates/inventory/delete_form.html`. Verify: affected pages render.
- **Batch 5 — Reports pre-rebuild legacy templates (3 files).** `reports/templates/reports/admin_dashboard.html`, `user_dashboard.html`, `request_form.html`. Verify: reports hub + admin queue render.
- **Batch 6 — Orphaned Python helper modules (3 files).** `contracts/managers.py`, `users/sql_fix.py`, plus the stray `contracts/static/js/supplier_modal.js`. Verify: `manage.py check` + processing/contract forms open supplier modal.
- **Batch 7 — Sales legacy RFQ endpoints (8 URL names + their views).** Remove the eight Tier-A `sales:rfq_*` / `supplier_search_ajax` / `quote_select_for_bid` routes and view functions in `sales/views/rfq.py` + `solicitations.py`. Verify: RFQ Center, queue send, solicitation workbench flows. (Larger — isolate to its own prompt.)
- **Batch 8 — Dead form classes (2).** `users.AnnouncementForm`, `processing.ProcessClinSplitForm`. Verify: `manage.py check`.
- **Batch 9 — Dead comment block (1).** Remove commented `ContractLifecycleDashboardView` in `contract_views.py:777-784`.

> **Tier B and C items are intentionally excluded** from deletion batches — they require human confirmation or must be kept.

---

## 5. Stale Documentation Note (observed, NOT modified)

Per instructions, no docs were edited. Record for a future documentation pass:

- **`PROJECT_STRUCTURE.md`** omits five installed apps: `sales`, `intake`, `core`, `imports`, `mailer`. Its app list (11) predates the current 16. It also lists a monolithic per-app `views.py` model, which no longer holds for `contracts`/`sales`/`processing` (package-based views).
- **`PROJECT_CONTEXT.md`** lists `processing` as owning `ProcessContractSplit`; the actual model is `ProcessClinSplit` (renamed in `processing/migrations/0019`).
- **Processing described as a fully-active standalone pipeline:** `processing/CONTEXT_processing.md` / `processing/AGENTS_processing.md` and `PROJECT_CONTEXT.md` describe processing as the ingestion pipeline without flagging that intake now runs a **parallel** draft workflow fed by the same nightly scrape. A "superseded-status / parallel-workflow" note would prevent future confusion (this audit's Phase 2 is the authoritative map until then).
- **`sales/DEAD_CODE_AUDIT.md` (2026-04-13)** is stale: it did not catch the shadowed `sales/views.py` module, and its 6 items are re-confirmed here (still orphaned). Consider superseding it with this report.
- **Docs referencing now-dead assets as live:** `suppliers/AGENTS_suppliers.md`/`CONTEXT_<app>.md` describe `supplier_enrich.js` and `contracts/.../supplier_modal.js` as bundled; `contracts/AGENTS_contracts.md`/`CONTEXT_<app>.md` still mention `log_payment_modal.html`. `docs/template_tracking.md` references the orphaned `status_toggle.html`.
- **Correct filename conventions for this repo** (for the future doc pass): `PROJECT_CONTEXT.md` at root; per-app `CONTEXT_<app>.md` + `AGENTS_<app>.md`; release notes in `release_notes/` with `README-rn.md` rules.

---

## 6. Verification Checklist

- [x] `python manage.py check` passes (nothing changed; re-run before any deletion prompt).
- [x] All `INSTALLED_APPS` apps covered.
- [x] Every Tier A entry cites the searches proving "no references."
- [x] No symbol appears in more than one tier.
- [x] Processing → Intake ledger includes the "% superseded / must-not-remove" sentence; known-LIVE processing surfaces (`SequenceNumber`, `pdf_parser`, `contract_utils`, `queue_we_won_awards` injection, `contracts` imports) confirmed LIVE.
- [x] Exactly one new file created (`docs/DEAD_CODE_AUDIT_2026-07-09.md`); no other repo changes.
