# Dead Code & Abandoned File Audit — STATZWeb

**Date:** 2026-10-19
**Branch:** `cleanup/dead-code-2026-10-19` (cut from `main` @ `340621e`, working tree clean)
**Phase:** A (read-only). This report is the only file added. No other file was modified, moved, or deleted.
**Predecessor:** `docs/DEAD_CODE_AUDIT_2026-07-09.md`. Most of its Tier A items were never removed and show up again below. The `sales` and `processing` apps it covered have since been decommissioned (`2abaa85`, `3fcfbc7`).

---

## 0. Summary

### Finding counts by tier and category

| Category | CONFIRMED DEAD | PROBABLY DEAD | LIVE BY INDIRECTION | UNWIRED BY DESIGN / RECENT | REVIEW ONLY - DB-COUPLED | NEEDS HUMAN DECISION | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| URL (A1) | 3 | 21 | 5 | 8 | 0 | 2 | 39 |
| VIEW (unrouted) | 2 | 1 | 1 | 0 | 0 | 0 | 4 |
| FILE (orphan modules, scratch, root files) | 3 | 8 | 3 | 3 | 1 | 11 | 29 |
| FUNC (functions, classes, constants, forms) | 4 | 16 | 1 | 9 | 0 | 0 | 30 |
| TPL (templates) | 5 | 12 | 3 | 0 | 0 | 0 | 20 |
| STATIC (assets, vendored, CDN) | 9 | 6 | 0 | 1 | 0 | 2 | 18 |
| CMD (management commands) | 0 | 0 | 1 | 3 | 0 | 5 | 9 |
| TAG / CP / MW / SIG | 1 | 0 | 3 | 1 | 0 | 0 | 5 |
| COMMENT / unreachable | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| IMPORT (unused imports / vars, grouped) | 0 | 0 | 1 | 0 | 0 | 3 | 4 |
| SQL | 0 | 0 | 0 | 0 | 7 | 0 | 7 |
| TEST | 0 | 0 | 0 | 5 | 0 | 0 | 5 |
| **Total** | **27** | **65** | **18** | **30** | **8** | **23** | **171** |

Each count is one table row. Some rows group several files or names: CMD-001 (25 live commands), TPL-013 (30 tailwind templates), STATIC-010 (9 letter-template files), URL-037 (3 route names), and the CMD-003/005/006/008/009 file groups.

### Proposed action counts

| Action | Count |
|---|---:|
| `REMOVE` | 78 (27 CONFIRMED DEAD + 51 PROBABLY DEAD) |
| `ASK` | 35 |
| `KEEP` | 58 |

### Estimated removable LOC (all 78 `REMOVE` rows)

| Kind | Lines |
|---|---:|
| Python (views, URL lines, orphan modules, helpers, forms, tags) | 1,922 |
| Templates (HTML, incl. the 72-line comment block) | 1,551 |
| First-party JS (`log_payment_modal.js`, `supplier_modal.js`, `portal_dashboard.js`, `supplier_enrich.js`) | 1,176 |
| Static text dumps (`morth.css`, `sandstone.css`, Word-exported letter `.htm` set) | 29,200 |
| Scratch / other (`_extra/tmp.js` 1,253, `temp_req.txt`, `contract_splits_README.md`, `server.crt`) | 1,557 |
| **Total text lines** | **35,406** |
| Binary assets | ≈ 7.1 MB (mp4 3.7 MB, two different JPEGs at the same collected path 2.9 MB, PNGs, zip) |

About 82% of the removable lines are three static dumps. The Python part is 1,922 lines.

### Latent bugs found along the way (not dead code; no action proposed in this task)

1. **`users:settings-view` cannot render.** `users/templates/users/settings_view.html:80` uses `{{ settings|get:settingName }}`. No `get` filter is registered, so the template fails at compile time with `TemplateSyntaxError: Invalid filter: 'get'`. Verified with `django.template.loader.get_template()`. This is part of the reason URL-001 is proposed for removal.
2. **`arcade:leaderboard` HTML branch renders a template that doesn't exist.** `arcade/views.py:307` renders `arcade/leaderboard.html`, and there is no such file. Only the JSON / XHR branch works (URL-033).
3. **`users/templates/users/manage_settings.html` calls URL names that don't exist** (`users:ajax_get_user_setting`, `users:ajax_get_setting_types`). It would raise `NoReverseMatch` if it were ever rendered. Its only view is unrouted (VIEW-003).
4. **`inventory/delete-item-ajax/<pk>/` is a destructive endpoint with no auth decorator.** Nothing calls it (`inventory/AGENTS_inventory.md:158` says the same). `LoginRequiredMiddleware` still requires a login, but it skips the `@conditional_login_required` check that its live twin `delete_item` has (URL-007).
5. **36 CDN references in 21 templates**, including `base_template.html` (jQuery, Bootstrap, Bootstrap Icons). This conflicts with the project's no-CDN rule (STATIC-018).

---

## 1. Method

### A0 Baseline

| Item | Result |
|---|---|
| `git status` | clean on `main` @ `340621e` |
| Branch | `cleanup/dead-code-2026-10-19` created |
| CI test command (`.github/workflows/python-app.yml`) | `python manage.py test` with `DJANGO_SETTINGS_MODULE=STATZWeb.settings`, `SECRET_KEY=ci-placeholder-key-not-for-production` (SQLite, because `IS_TESTING` is set). CI also runs `flake8 . --count --select=E9,F63,F7,F82`. `pytest.ini` exists for local use only. |
| URL snapshot | `url_snapshot_before.txt` in the OS temp dir (session scratchpad), **1,083 lines** (route ⇥ namespaced name ⇥ dotted callable). Produced with `manage.py shell` and an inline walker over `get_resolver().url_patterns`. A scratch settings module that overrides only `DATABASES` with a temp SQLite file was used, so the real dev SQL Server was never contacted. |
| `manage.py check` (same scratch settings) | `System check identified no issues (0 silenced).` |
| Tools | `ruff`: not installed, skipped. `vulture`: not installed, skipped. `coverage`: installed but not run, because a full coverage run is a full test run and adds little to static evidence. `flake8` 7.1.1 is installed and used by CI. It was run read-only as `python -m flake8 --select=F401,F841` (the `.venv/Scripts/flake8.exe` shim is broken, so it was called via `-m`). |

### A0.3 Inventory (tracked files, `git ls-files`; 1,692 files total)

| App | .py files | Python LOC | views | urls | forms | services/utils | templatetags | mgmt cmds | migrations | tests | templates | app static | other modules |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `STATZWeb` | 20 | 2,631 | 1 | 1 | 0 | 2 | 0 | 5 | 0 | 2 | 0 | 0 | context_processors.py, middleware.py |
| `users` | 58 | 7,683 | 1 | 1 | 2 | 2 | 5 | 16 | 15 | 1 | 53 | 3 | admin, apps, context_processors, middleware, models, signals |
| `inventory` | 15 | 316 | 1 | 1 | 1 | 0 | 2 | 0 | 5 | 1 | 3 | 0 | admin, apps, models |
| `imports` | 13 | 845 | 1 | 1 | 0 | 1 | 2 | 0 | 2 | 1 | 0 | 0 | admin, apps, models |
| `contracts` | 238 | 42,312 | 36 | 2 | 1 | 48 | 1 | 9 | 107 | 27 | 85 | 24 | admin, apps, context_processors, models, signals |
| `dibbs` | 88 | 14,185 | 12 | 1 | 1 | 22 | 2 | 7 | 6 | 14 | 16 | 0 | admin, apps, context_processors, signals, models/ pkg |
| `accesslog` | 14 | 474 | 1 | 1 | 1 | 0 | 0 | 0 | 6 | 1 | 2 | 0 | admin, apps, models |
| `mailer` | 20 | 1,402 | 1 | 1 | 1 | 3 | 0 | 0 | 5 | 1 | 8 | 0 | admin, apps, models |
| `intake` | 34 | 11,743 | 1 | 1 | 1 | 6 | 2 | 3 | 6 | 1 | 6 | 1 | admin, apps, models |
| `training` | 23 | 3,104 | 1 | 1 | 1 | 0 | 3 | 0 | 12 | 1 | 16 | 0 | admin, apps, models |
| `reports` | 14 | 1,815 | 1 | 1 | 1 | 2 | 0 | 0 | 4 | 1 | 10 | 0 | admin, apps, models |
| `suppliers` | 39 | 4,911 | 2 | 2 | 0 | 1 | 0 | 0 | 16 | 4 | 0 | 0 | admin, apps, models (+ `portal/` API pkg) |
| `products` | 25 | 1,787 | 1 | 1 | 1 | 2 | 2 | 3 | 6 | 5 | 0 | 0 | admin, apps, models |
| `tools` | 26 | 4,473 | 2 | 1 | 0 | 8 | 0 | 3 | 3 | 4 | 2 | 1 | admin, apps, models |
| `transactions` | 14 | 1,145 | 1 | 1 | 1 | 1 | 0 | 0 | 3 | 0 | 4 | 0 | admin, apps, middleware, models, signals |
| `arcade` | 36 | 4,971 | 2 | 1 | 0 | 2 | 0 | 3 | 5 | 7 | 0 | 24 | admin, apps, models |
| `core` | 20 | 1,580 | 1 | 1 | 0 | 0 | 0 | 2 | 6 | 1 | 8 | 0 | admin, apps, context_processors, models |
| `quote` | 86 | 16,371 | 12 | 1 | 1 | 20 | 0 | 2 | 12 | 19 | 26 | 7 | admin, apps, signals, models/ pkg |
| **Total** | **783** | **121,748** | | | | | | | | | | | |

Column notes: "views" counts view modules (a package counts each file). "templates" counts files under `<app>/templates/`. Project-level `templates/` has 42 files and `static/` has 184 (127 of them are the committed Django admin copy). Third-party apps (`crispy_*`, `corsheaders`, `django_extensions`, `django_browser_reload`, `django.contrib.*`) are out of scope.

### Search methodology (used in every Evidence cell)

- **WB(x):** word-boundary token search for `x` across **all** tracked text files: `.py` (including migrations, tests, `_extra`), `.html`, `.js`, `.css`, `.md`, `.mdc`, `.txt`, `.json`, `.sh`, `.yml`, `.job`, `.xml`, `.htm`. Hit counts exclude the definition itself and are split as code / test / doc.
- **IMP(m):** AST import graph built from `ast.walk` over every `.py` file. It therefore includes indented (lazy, function-body) imports, relative imports, and `from pkg import mod` forms. It also includes a dotted-string search for `m` in every text file (settings, docs, WebJob scripts).
- **URL-P1(name):** Django reverse forms. These are `{% url 'ns:name' %}` / `{% url 'name' %}`, `reverse(`, `reverse_lazy(`, `redirect(`, `resolve_url(`, and `HttpResponseRedirect(` with the bare or namespaced name, plus any quoted `'ns:name'` literal and `url_name`/`view_name` comparisons. Searched in `.py/.html/.js/.json/.txt/.xml`, excluding the defining `name=` and `docs/`, `release_notes/`, `.cursor/`, `_extra/`.
- **URL-P2(route):** hardcoded-path search for the route's static prefix with a leading `/`, cut at the first `<`, in the same file set minus `urls.py` and tests. That covers `fetch(`, `$.ajax`, `data-url`, `href="/…"`, `sw.js` precache, nav menus, and Python constants. A prefix shared with a live route counts as a hit, so P2 can miss dead routes but never wrongly marks a live one dead.
- **PATH(p):** substring search for a template's or asset's path relative to `templates/` or `static/`, plus its basename, in every text file. This catches `render()`, `template_name`, `get_template`, `render_to_string`, `{% extends %}`, `{% include %}`, `{% static %}`, CSS `url()`, and JS module imports.
- **Dynamic builders checked by hand:** `render(request, f'quote/research/_panel_{panel}.html')` (`quote/research_views.py:92`), `f"arcade/{game_key}.html"` (`arcade/views.py:101`), the JS path builders in `folder_scan_status.js:52` and `dibbs/import/progress.html:191`, and the Django admin template override path convention.
- **Template existence:** every literal template name found in `render`/`render_to_string`/`get_template`/`template_name`/`{% include %}`/`{% extends %}` (230 names) was loaded with `get_template()`. Every routed CBV that renders a template (61) was instantiated and checked with `get_template_names()` and `select_template()`.
- **Shadowing:** every one of the 1,083 snapshot routes was turned into a sample path (`<int>`→`7`, `<str>`→`abc`, …) and passed to `resolve()`. **All 1,083 resolved to their own pattern, so there are no shadowed or regex-equivalent duplicates.** Exact-duplicate routes: 0. Duplicate URL *names* (aliases): `inventory:dashboard` (2), `contracts:supplier_search` (2), `accesslog:visitor_log` (2). These are intentional aliases, and the redundant ones are listed as findings.
- **A4 forensics:** "Last touched" for a *symbol* or *URL line* is the newest `committer-time` from `git blame --line-porcelain -L start,end`, which follows renames. For a *file* it is `git log -1 --format=%cs`. The file's own last commit is given too where it differs. `git log -S<symbol>` (pickaxe) was run for each symbol to find the commit that removed its last caller. Thresholds: **RECENT** ≥ 2026-07-21 (90 days); **>12 mo** < 2025-10-19.
- **Tier rule for routed endpoints:** a routed URL can always be reached by a typed or bookmarked URL, which the repo can't rule out. So a zero-reference **HTML page** is capped at PROBABLY DEAD with `ASK`. A zero-reference **AJAX/JSON endpoint** with no JS caller follows the normal age rules.
- **Nightly-path rule:** symbols in modules reached by the `run-scrape-awards` / `run-auto-import-dibbs` WebJobs are marked `ASK`, not `REMOVE`, even when unreferenced. This keeps the "never touch the nightly scripts" constraint conservative.

### A2 indirection checklist (column "Indirection checks done")

Codes used in tables. **ALL** means every check below was run for that row; any check that turned something up is named.

| Code | Check | Global result |
|---|---|---|
| R | Permission/access registries | `LoginRequiredMiddleware` keys access by **URL namespace → `AppRegistry.app_name`** (`STATZWeb/middleware.py:101-141`), never by URL name. The public-URL list is path-prefix based (`is_public_url`). The nav and context processors (`reminders_processor`, `active_users_processor`, `user_preferences`, `unread_messages`, `active_company`, `version_context`, `cache_version_context`, `dibbs_notice_count`, `release_notes_context`, `api_budget`) were searched like any other code. |
| S | Settings dotted strings | `MIDDLEWARE` (16 entries), `TEMPLATES.context_processors` (14), `LOGGING`, `TASK_FUNCTIONS` (10 entries, `core/management/commands/run_background_tasks.py:22-33`). |
| D | Dynamic dispatch | `importlib.import_module` appears only in `contracts/utils/excel_utils.py:12` / `image_processing.py:12` (lazy third-party loads) and one test. `import_string(`, `globals()[` and `__import__(` appear nowhere except `finance_line_views.py:434` (`datetime`). Dispatch dicts: `TASK_FUNCTIONS`, arcade registry, quote research panel f-string. |
| L | Lazy imports | Covered by the AST `ast.walk` import graph. |
| G | Signals, admin, template tags, middleware | `@receiver`s and `apps.py ready()` imports for `contracts`, `quote`, `transactions` and `users` signals. Every `@admin.register` class. `{% load %}` sites plus per-tag usage for all 12 tag libraries. |
| T | Registries | `transactions/signals.py:16` `TRACKED` (models + fields only, no views). The arcade `registry.py` list. |
| W | Ops wiring | `webjobs/*/run.sh` + `settings.job` (`run_background_tasks`, `process_contract_log_exports`, `auto_import_dibbs`, `fetch_pending_pdfs`, `scrape_awards`), `startup.sh` (`set_build_info`, `collectstatic`, `import_release_notes`, `verify_stored_procs`, optional `migrate`), `.github/workflows/python-app.yml`, `.deployment`, `Procfile`, `web.config`. |
| Doc | Docs | `CONTEXT.md`, `AGENTS.md` (the repo uses `AGENTS.md`; there is no `AGENT.md`), `PROJECT_CONTEXT.md`, `PROJECT_AGENTS.md`, `PROJECT_STRUCTURE.md`, every `CONTEXT_<app>.md` / `AGENTS_<app>.md`, `release_notes/README-rn.md` and all release notes. **`published: false` notes:** the arcade set (2026-08-14/17/18), `calendar-two-way-sharepoint-sync` (2026-08-17), `open-sols-filter-rail` (2026-10-15), plus several 2026-06/07 notes. Staged work checked: Folder Scan / Folder Review Stage A+B, Scan Inbox, Award Intake Ledger, the reminders upgrade (`b426522`, 2026-10-07), the DIBBS Notices redesign, and the contract-log export job (`5c3f61f`, 2026-09-02). |
| Tst | Tests | A reference that appears only in a test is reported as "test-only". |

---

## 2. URL ↔ View comparison (A1)

Removing a URL row also removes the view it names when that view has no other route. The dependents are listed in "Proposed action".

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| URL-001 | `users/urls.py:29` → `users/views.py:715-729` | `users:settings-view` → `user_settings_view` (+ `users/templates/users/settings_view.html`) | PROBABLY DEAD | URL-P1(`settings-view`)=0; URL-P2(`/users/settings/view/`)=0 code (3 doc: `.cursor/rules/user-settings-rule.mdc`, `users/AGENTS_users.md`, `users/CONTEXT_users.md`). WB(`user_settings_view`)=0 outside urls.py. `get_template('users/settings_view.html')` → **TemplateSyntaxError "Invalid filter: 'get'"** | URL line 2025-05-28; view 2025-10-15; template 2026-04-22 (`915aea8`) | ALL; Doc: CONTEXT_users.md:112,122 (stale: says this route renders `manage_settings.html`) | REMOVE: URL line, view, and TPL-017. The page throws a compile error on every request, so no working user path can depend on it. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-002 | `users/urls.py:30` → `users/views.py:537-584` | `users:settings-get` → `ajax_get_user_setting` | CONFIRMED DEAD | URL-P1(`settings-get`)=0; URL-P2(`/users/settings/ajax/get/`)=0. WB(`ajax_get_user_setting`): only `users/templates/users/manage_settings.html:94` via the **non-existent** name `users:ajax_get_user_setting` (template is itself dead, TPL-016) | 2025-05-28 / view 2025-04-02 | ALL | REMOVE: URL line and view |
| URL-003 | `users/urls.py:32` → `users/views.py:586-611` | `users:settings-types` → `ajax_get_setting_types` | CONFIRMED DEAD | URL-P1(`settings-types`)=0; URL-P2(`/users/settings/ajax/types/`)=0. WB: only `manage_settings.html:181,422` via the non-existent name `users:ajax_get_setting_types` | 2025-05-28 / view 2025-04-22 | ALL | REMOVE: URL line and view |
| URL-004 | `users/urls.py:62` → `users/views.py:908-924` | `users:portal_dashboard_data` → `portal_dashboard_data` | PROBABLY DEAD | URL-P1=0; URL-P2(`/users/portal/dashboard/`)=0 code (2 doc). Only consumer would be `static/js/portal_dashboard.js`, which no template loads (PATH=0) and whose required DOM ids `portal-context-data` / `portalDashboardConfig` appear nowhere else | 2025-10-31 | ALL; Doc: CONTEXT_users.md:81,124 (stale) | REMOVE: URL line, view, and STATIC-014. Doubt is age only (3–12 mo). The Sept 2026 portal-home redesign does not use it. |
| URL-005 | `users/urls.py:67` → `users/views.py:1043-1055` | `users:portal_task_create` → `portal_task_create` | PROBABLY DEAD | URL-P1=0; URL-P2(`/users/portal/tasks/create/`)=0 code (1 doc) | 2025-10-31 | ALL; Doc: CONTEXT_users.md:84 | REMOVE: URL line and view (JSON POST endpoint, no caller). Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-006 | `users/urls.py:69` → `users/views.py:1531-1547` | `users:portal_import_sharepoint_xlsx` | NEEDS HUMAN DECISION | URL-P1=0; URL-P2(`/users/portal/events/import/sharepoint/`)=0 | view 2026-04-17 (`40eb8f6` "Add SharePoint calendar sync") | ALL; Doc: the release note `2026-08-17-calendar-two-way-sharepoint-sync` is **`published: false`**, so this belongs to a feature that may still be staged | ASK |
| URL-007 | `inventory/urls.py:23` → `inventory/views.py:62-67` | `inventory:delete_item_ajax` → `delete_item_ajax` | CONFIRMED DEAD | URL-P1=0; URL-P2(`/inventory/delete-item-ajax/`)=0 code (2 doc). Dashboard JS posts to `/inventory/delete-item/<pk>/` (`delete_item`) | 2025-02-12 | ALL; Doc: AGENTS_inventory.md:97,158 ("No client currently uses it"), CONTEXT_inventory.md:65,80,107 | REMOVE: URL line and view. It is an unused destructive endpoint without the auth decorator. |
| URL-008 | `contracts/urls.py:376` → `contract_log_views.py:276-414` | `contracts:export_contract_log` | UNWIRED BY DESIGN / RECENT | URL-P1=0; URL-P2(`/contracts/log/export/`)=0 code | view 2026-08-31 (`5c3f61f` "Add contract log export job functionality") | ALL; W: `process_contract_log_exports` WebJob | KEEP |
| URL-009 | `contracts/urls.py:377` → `contract_log_views.py:417-448` | `contracts:export_contract_log_xlsx` | UNWIRED BY DESIGN / RECENT | URL-P1=0; URL-P2(`/contracts/log/export-xlsx/`)=0 | view 2026-09-02 | ALL (same cluster as URL-008) | KEEP |
| URL-010 | `contracts/urls.py:382` → `contract_log_views.py:509-522` | `contracts:open_export_folder` | UNWIRED BY DESIGN / RECENT | URL-P1=0; URL-P2(`/contracts/open-export-folder/`)=0 code (1 doc) | view 2026-05-22; module 2026-09-02 | ALL; part of the export-job cluster that is mid-rework | KEEP |
| URL-011 | `contracts/urls.py:426` | `contracts:clin_create` (alias of `ClinCreateView`, canonical `contracts:contract_clin_create`) | PROBABLY DEAD | URL-P1(`clin_create`)=0 (`contract_clin_create` hits are a different name); URL-P2(`/contracts/clin/new/`)=0 code (2 doc) | 2025-12-15 | ALL; Doc: CONTEXT_contracts.md:171 lists the path | ASK (HTML page alias, could be bookmarked) |
| URL-012 | `contracts/urls.py:437` → `clin_views.py:194-218` | `contracts:clin_acknowledgment_update` → `ClinAcknowledgmentUpdateView` (+ `contracts/templates/contracts/clin_acknowledgment_form.html`) | PROBABLY DEAD | URL-P1=0; URL-P2(`/contracts/clin/acknowledgment/`)=0 code (1 doc). WB(`ClinAcknowledgmentUpdateView`)=1 (`contracts/views/__init__.py` re-export) + 1 doc | URL 2025-12-15; view 2025-03-04 | ALL; Doc: CONTEXT_contracts.md | ASK (HTML form page). If approved, the template goes with it. |
| URL-013 | `contracts/urls.py:441` | `contracts:supplier_list` (alias; canonical `suppliers:supplier_list` → same view) | PROBABLY DEAD | URL-P1(`contracts:supplier_list`)=0 (all links use `suppliers:supplier_list`); URL-P2(`/contracts/suppliers/`)=0 code | 2025-12-15 | ALL; Doc: CONTEXT_contracts.md:354 | ASK (HTML alias) |
| URL-014 | `contracts/urls.py:443` | `contracts:supplier_autocomplete` (alias; canonical `suppliers:supplier_autocomplete`) | PROBABLY DEAD | URL-P1=0; URL-P2(`/contracts/suppliers/autocomplete/`)=0 | 2025-12-15 | ALL | REMOVE: URL line only (AJAX alias; the view stays live under `suppliers:`). Doubt is the age of a non-mechanical `urls.py` commit only. |
| URL-015 | `contracts/urls.py:445` | `contracts:supplier_search` (`suppliers/search/`) → `SupplierSearchView` | UNWIRED BY DESIGN / RECENT | URL-P1=0; URL-P2(`/contracts/suppliers/search/`)=0 | URL 2025-12-15; **view 2026-08-13** (`6cb3e33` supplier alias management) | ALL | KEEP (the view was edited inside the 90-day window) |
| URL-016 | `contracts/urls.py:774` → `idiq_views.py:211-228` | `contracts:supplier_search` (`supplier/search/`) duplicate name | UNWIRED BY DESIGN / RECENT | URL-P1=0; URL-P2(`/contracts/supplier/search/`)=0 | view 2026-08-13 | ALL | KEEP |
| URL-017 | `contracts/urls.py:446` | `contracts:supplier_edit` (alias; canonical `suppliers:supplier_edit`) | PROBABLY DEAD | URL-P1=0; URL-P2(`/contracts/supplier/`) shares a prefix with live routes and was checked by hand: 0 for `/edit/` | 2025-12-15 | ALL; Doc: CONTEXT_contracts.md:354 | ASK (HTML alias) |
| URL-018 | `contracts/urls.py:447` | `contracts:supplier_create` (alias; canonical `suppliers:supplier_create`) | PROBABLY DEAD | URL-P1=0 (`supplier_modal.html:15` uses `suppliers:supplier_create`); URL-P2 by hand(`/contracts/supplier/create/`)=0 | 2025-12-15 | ALL; Doc: CONTEXT_contracts.md:354 | ASK (HTML alias) |
| URL-019 | `contracts/urls.py:523` → `supplier_views.py:1069-1078` | `contracts:supplier_get_certification` → `get_supplier_certification` | PROBABLY DEAD | URL-P1=0; URL-P2(`/contracts/supplier/certification/`)=0; `git grep "certification/"` in .js/.html = 0. WB(view)=1 (`__init__` re-export) | view 2025-12-03; URL 2025-12-15 | ALL; pickaxe: 0 callers ever | REMOVE: URL line, view, and `__init__` re-export (JSON endpoint). Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-020 | `contracts/urls.py:543` → `supplier_views.py:1212-1220` | `contracts:supplier_get_classification` → `get_supplier_classification` | PROBABLY DEAD | URL-P1=0; URL-P2(`/contracts/supplier/classification/`)=0; `git grep "classification/"` .js/.html = 0 | view 2025-12-03 | ALL; pickaxe: 0 callers ever | REMOVE: URL line, view, and re-export. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-021 | `contracts/urls.py:554`; alias `reminder_views.py:74` | `contracts:create_reminder` (`create_reminder = add_reminder`) | UNWIRED BY DESIGN / RECENT | URL-P1=0 (the `'create_reminder'` strings in `notes_popup.html` / `note_modal.html` / `note_views.py` are a POST field name, not a URL); URL-P2(`/contracts/reminder/create/`)=0 | line 2025-12-15; `reminder_views.py` 2026-10-07 (`b426522` reminders upgrade) | ALL; Doc: release note `2026-10-07-set-check-in-reminders-review` | KEEP (reminders upgrade is in flight) |
| URL-022 | `contracts/urls.py:555` | `contracts:add_note_reminder` (alias of `add_reminder`) | UNWIRED BY DESIGN / RECENT | URL-P1=0; URL-P2(`/contracts/reminder/add/`)=0 code (1 doc: CONTRACTS_APP_CURRENT_STATE.md:54) | as URL-021 | ALL | KEEP |
| URL-023 | `contracts/urls.py:681` → `api_views.py:502-562` | `contracts:api_buyer_create` → `create_buyer` | PROBABLY DEAD | URL-P1=0; URL-P2(`/contracts/api/buyers/create/`)=0. WB(`create_buyer`): the intake hits are `_create_buyer`, a different function | view 2025-10-24 | ALL; Doc: intake/AGENTS_intake.md:294 is about `_create_buyer` | REMOVE: URL line and view (JSON). Doubt is age only. |
| URL-024 | `contracts/urls.py:685` → `contract_views.py:580-591` | `contracts:check_contract_number` → `check_contract_number` | PROBABLY DEAD | URL-P1=0; URL-P2(`/contracts/check-contract-number/`)=0 | view 2025-03-12; URL line 2025-12-15 | ALL; pickaxe(`check_contract_number`): 0 callers ever | REMOVE: URL line and view (JSON). The only recent touch is the Dec-2025 `urls.py` edit. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-025 | `contracts/urls.py:751` → `idiq_views.py:98-146` | `contracts:idiq_contract_detail_create` → `IdiqContractDetailsCreateView` | PROBABLY DEAD | URL-P1=0; `git grep "details/create"` = 0 | view 2025-03-27 | ALL; Doc: CONTEXT_contracts.md, products/CONTEXT_products.md | ASK (HTML form) |
| URL-026 | `contracts/urls.py:756` → `idiq_views.py:148-191` | `contracts:idiq_contract_detail_delete` → `IdiqContractDetailsDeleteView` | PROBABLY DEAD | URL-P1=0; `git grep "details/.*delete"` = 0 | view 2025-03-27 | ALL; Doc: products/CONTEXT_products.md | ASK (HTML form) |
| URL-027 | `contracts/urls.py:787` → `finance_views.py:567-615` | `contracts:update_contract_level_charge` → `update_contract_level_charge` | PROBABLY DEAD | URL-P1=0; URL-P2(`/contracts/api/contract-level-charge/`)=0 (live JS uses `/contracts/api/level-charges/…`) | view 2026-06-01 (`f581aef`, App Insights instrumentation) | ALL | REMOVE: URL line, view, and `__init__` import (JSON). Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-028 | `contracts/urls.py:1049` → `contracts/views/admin_tools.py` | `contracts:admin_tools` → `supplier_admin_tools` (+ `contracts/admin_tools.html`) | NEEDS HUMAN DECISION | URL-P1=0; URL-P2(`/contracts/admin-tools/`)=0 code | 2025-12-02 | ALL; Doc: CONTEXT_contracts.md:237,273,367,374,516 document it as a live **superuser tool reached by typed URL** | ASK |
| URL-029 | `products/urls.py:14` | `products:nsn_search` (alias; canonical `contracts:nsn_search` → same `NsnSearchView`) | PROBABLY DEAD | URL-P1(`products:nsn_search`)=0 (`nsn_modal.html:15` uses `contracts:nsn_search`); URL-P2(`/products/nsn/search/`)=0 | 2025-12-03 | ALL | REMOVE: URL line only (AJAX alias). Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-030 | `training/urls.py:11` | `training:manage_matrix_for_account` (alias of `manage_matrix`) | PROBABLY DEAD | URL-P1=0; URL-P2(`/training/matrix/manage/`)=0 code (3 doc) | 2025-05-08 | ALL; Doc: training AGENTS/CONTEXT + `training/Docs/Training App write-up.md` | ASK (HTML page alias with an account pre-select) |
| URL-031 | `transactions/urls.py:25` → `transactions/views.py:47-58` | `transactions:field_info` → `field_info_api` | PROBABLY DEAD | URL-P1=0; URL-P2(`/transactions/api/field-info/`)=0 code (2 doc) | 2026-02-12 | ALL; T: `TRACKED` names models only | REMOVE: URL line and view (JSON). Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-032 | `contracts/urls.py:905` → `acknowledgment_views.py:275-289` | `contracts:get_acknowledgment_letter` → `get_acknowledgment_letter` | PROBABLY DEAD | URL-P1=0; URL-P2 hit `acknowledgment_letter_form.html:160` is the different route `/contracts/acknowledgment-letter/<id>/update/`; exact route `/contracts/acknowledgment-letter/<clin_id>/` = 0 | view 2026-05-21 | ALL; Doc: CONTEXT_contracts.md:352 says it was superseded by `acknowledgment-letter-page` | REMOVE: URL line, view, and both `__init__` entries (JSON). Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| URL-033 | `arcade/views.py:288-316` | `arcade:leaderboard` HTML branch → missing `arcade/leaderboard.html` (A1.5) | UNWIRED BY DESIGN / RECENT | `get_template('arcade/leaderboard.html')` → TemplateDoesNotExist; the JSON branch is live | 2026-08-17 | ALL; Doc: arcade notes are `published: false` | KEEP (latent bug; puzzle code is outside this task) |
| URL-034 | `users/urls.py:45` | `users:microsoft_callback` | LIVE BY INDIRECTION | URL-P1=0 | 2025-09-05 | R: middleware bypasses any `microsoft` path; this is the OAuth redirect URI registered in Azure AD (external) | KEEP |
| URL-035 | `suppliers/portal/urls.py:11` | `supplier_portal:send_email` | LIVE BY INDIRECTION | URL-P1=0 code, 1 test | 2026-07-20 | External supplier-portal API client (versioned `api/supplier-portal/v1/`) | KEEP |
| URL-036 | `contracts/urls.py:980` | `contracts:folder_scan_status_json` | LIVE BY INDIRECTION | URL-P1=0 | 2026-10-01 | D: `contracts/static/contracts/js/folder_scan_status.js:52` builds `pathname + '/status.json'` | KEEP |
| URL-037 | `dibbs/urls.py:48-50` | `dibbs:import_step_parse` / `_solicitations` / `_lines` | LIVE BY INDIRECTION | URL-P1=0 | 2026-09-25 | D: `dibbs/templates/dibbs/import/progress.html:191-208` builds `BASE + 'step/' + name` | KEEP |
| URL-038 | `STATZWeb/urls.py:136-137` | `manifest`, `service_worker` | LIVE BY INDIRECTION | URL-P1=0 | 2026-01-12 | R/W: hardcoded `/manifest.json`, `/sw.js` in `STATZWeb/middleware.py:62-64,168-173` and the PWA | KEEP |
| URL-039 | `STATZWeb/urls.py:105` | commented-out `# path('check-auth-method/', views.check_auth_method, …)` (A1.2) | PROBABLY DEAD | Only commented pattern in any `urls.py` (`^\s*#\s*(re_)?path\(` → 1). `views.check_auth_method` does not exist | 2026-01-12 | ALL | REMOVE: the comment line. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |

URL-037 covers three route names (`import_step_parse`, `_solicitations`, `_lines`) and URL-038 covers two (`manifest`, `service_worker`).

Notes on the other A1 checks: A1.3 found no shadowed duplicates (see Method). A1.5 found missing or broken templates in URL-001, URL-033, TPL-009/010 (which extend a non-existent `base.html`) and TPL-016.

---

## 3. Unrouted views (A1.1)

The AST scan covered every function and class in every views module (`*/views.py`, `*/views/*.py`, `views_*.py`) and compared them with the 1,083 snapshot callables. 41 were unrouted. 37 of those are helpers used inside their own module (e.g. `training.views.get_completion_status`, `suppliers.views.compute_health_data`), mixins (`ActiveCompanyQuerysetMixin`, `SuperuserRequiredMixin`, `PortalAPIView`), or shared helpers imported elsewhere (`quote.views.quote_save.save_response`, `note_views.annotate_notes_for_current_user`). None of those are findings. The other four:

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| VIEW-001 | `contracts/views/shipment_views.py:224-244` | `get_shipment` (`@require_http_methods(["GET"])`) | PROBABLY DEAD | not in snapshot; WB(`get_shipment`)=0 outside def; not re-exported in `contracts/views/__init__.py` | 2026-04-21 | ALL; pickaxe: 2 commits, no caller ever | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| VIEW-002 | `users/views.py:437-470` | `save_user_setting` | CONFIRMED DEAD | not in snapshot; WB=0 code, 3 doc (`users/CONTEXT_users.md:204`, old audit). The live endpoint is `users:settings-save` → `ajax_save_setting` | 2025-05-14 | ALL; Doc stale | REMOVE |
| VIEW-003 | `users/views.py:472-496` | `manage_settings` (renders `users/manage_settings.html`) | CONFIRMED DEAD | not in snapshot; WB=0 code (1 self), 8 doc (`users/CONTEXT_users.md`, `users/README.md`) | 2025-04-02 | ALL | REMOVE, together with TPL-016 |
| VIEW-004 | `users/views.py:367-369` | `on_user_logged_out` | LIVE BY INDIRECTION | WB=0, but decorated `@receiver(user_logged_out)` | 2025-02-11 | G: signal receiver | KEEP |

---

## 4. Orphan modules, scratch, backup, and root files (A3.1, A3.2)

`IMP(m)` returned no code importer for any module below. The backup/copy name search covered `*_old*`, `*_bak*`, `*copy*`, `*_v2*`, `*_new*`, `*.orig`, `*.rej`, `*~`, `*.pyc`, `temp_*`, `tmp_*`. Matches: `_extra/temp_contract_log_views.py`, `_extra/temp_req.txt`, `_extra/tmp_read_xlsx.py`, `_tmp_render_check.py`, `contracts/migrations/remove_old_payment_history.py`. The other name matches are release notes and `whats_new.html`, which are live. No `.pyc`, `.orig`, `.rej` or `~` files are tracked.

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| FILE-001 | `STATZWeb/pdf_security.py` (86 LOC) | `safe_pdf_processing`, `get_pdf_security_settings`, … | CONFIRMED DEAD | IMP(`STATZWeb.pdf_security`)=0; WB(`pdf_security`)=0 code, 1 doc (old audit); WB(`safe_pdf_processing`)=0; `settings.py` defines `PDF_MAX_*` directly | 2025-09-22 | ALL | REMOVE |
| FILE-002 | `contracts/managers.py` (10) | `ActiveUserManager`, `User.active_objects` monkey-patch | CONFIRMED DEAD | IMP(`contracts.managers`)=0; `from .managers`=0; WB(`ActiveUserManager`)=0; WB(`active_objects`)=0 | 2025-03-12 | ALL; the module is never imported, so the monkey-patch never runs | REMOVE |
| FILE-003 | `users/sql_fix.py` (37) | `create_app_registry_table` (`__main__` script with raw SQL) | NEEDS HUMAN DECISION | IMP=0; WB(`sql_fix`)=0 code, 3 doc | 2025-02-27 | ALL; Doc: CONTEXT_users.md:73,148,203 describe it as a manual SQL Server repair tool | ASK (one-time repair) |
| FILE-004 | `suppliers/utils.py` (226) | `scrape_supplier_site` | PROBABLY DEAD | IMP(`suppliers.utils`)=0; `from .utils` in suppliers = 0; WB(`scrape_supplier_site`)=0 code, 9 doc | 2025-12-04 | ALL; Doc: AGENTS_suppliers.md:71 says "Treat it as dead code until confirmed otherwise", :212 "not wired" | REMOVE (the docs already call it dead; doubt is age only) |
| FILE-005 | `contracts/utils/image_processing.py` (42) | lazy `np()`, `fitz()`, `pypdf()`, … | CONFIRMED DEAD | IMP(`contracts.utils.image_processing`)=0; WB(`image_processing`)=0 code, 2 doc | 2025-09-22 | ALL; D: its own `importlib.import_module` is internal only | REMOVE; update CONTEXT_contracts.md:35 and README-utils.md |
| FILE-006 | `dibbs/services/ca_parser.py` (165) | `parse_ca_zip` | UNWIRED BY DESIGN / RECENT | IMP(`dibbs.services.ca_parser`)=0 | 2026-09-25 (moved in `3fcfbc7`) | ALL; Doc: sales_DIBBS_System_Spec.md:3325 calls it an "optional legacy/ad-hoc bulk path" | KEEP (90-day rule). Re-audit after 2026-12-24. |
| FILE-007 | `_tmp_render_check.py` (repo root, 34) | throwaway render check | PROBABLY DEAD | IMP=0; PATH=0 code | 2026-05-13 | ALL | REMOVE (stray root file; `Work-Business/CLAUDE.md` forbids those). Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FILE-008 | `scratch/test_stage_1.py` (190) | ad-hoc script | PROBABLY DEAD | IMP=0; it imports `processing.models` (line 12), and the `processing` app is gone, so it raises ImportError | 2026-06-01 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FILE-009 | `_extra/temp_contract_log_views.py` (275) | old copy of `contract_log_views` | PROBABLY DEAD | IMP=0; `ast.parse` fails (U+FEFF BOM); duplicate of live functions | 2026-04-29 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FILE-010 | `_extra/tmp_read_xlsx.py` (60) | scratch | PROBABLY DEAD | IMP=0; PATH=0; also fails `ast.parse` (BOM) | 2026-02-17 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FILE-011 | `_extra/tmp.js` (1,253) | scratch JS | PROBABLY DEAD | PATH(`tmp.js`)=0 | 2026-02-17 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FILE-012 | `_extra/temp_req.txt` (48) | stale requirements snapshot (Django 4.2.25 pin) | PROBABLY DEAD | PATH=0 | 2026-02-17 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FILE-013 | `_extra/dev_commands.py` (102) | dev helper | NEEDS HUMAN DECISION | IMP=0; PATH: `_extra/README.md` | 2026-02-17 | ALL; Doc: `_extra/README.md` | ASK |
| FILE-014 | `_extra/setup_dev.py` (85) | dev setup | NEEDS HUMAN DECISION | IMP=0 | 2026-02-17 | ALL | ASK |
| FILE-015 | `_extra/test_azure_db_connection.py` (209) | connection diagnostic | NEEDS HUMAN DECISION | IMP=0; excluded from pytest (`norecursedirs`) | 2026-02-17 | ALL | ASK |
| FILE-016 | `_extra/test_open_system_test.py`, `_extra/test_system_tests.py`, `_extra/test_version_display.py` (1 line each) | **blank files** (whitespace only) | PROBABLY DEAD | contents = one blank line | 2026-02-17 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FILE-017 | `_extra/VISUAL_TEST.html` (141) | dev visual test page | NEEDS HUMAN DECISION | PATH=0 | 2026-02-17 | ALL | ASK |
| FILE-018 | `_extra/htaccess.conf` (70) | Apache/IIS config for `C:/inetpub/...` | NEEDS HUMAN DECISION | PATH=0; references `staticfiles/certificates` (STATIC-004) | 2026-02-17 | ALL; W: not used by Azure Linux (`startup.sh`) | ASK |
| FILE-019 | `_extra/themeing.md` (300), `_extra/README.md` (30) | docs | NEEDS HUMAN DECISION | PATH: `README.md` indexes the folder; WB(`themeing`)=0 code | 2026-04-16 / 2026-02-17 | Doc | KEEP |
| FILE-020 | `_extra/env.dev.example` (33) | env template | UNWIRED BY DESIGN / RECENT | PATH=0 code (copied by hand) | 2026-09-28 | ALL | KEEP |
| FILE-021 | `web.config` (15) | IIS `httpPlatformHandler` → `D:\home\Python39\python.exe manage.py runserver` | NEEDS HUMAN DECISION | not referenced; the platform is Azure Linux (`startup.sh` → gunicorn) | 2025-09-22 | W | ASK (it would run Django `runserver` on Python 3.9 if a Windows host ever read it) |
| FILE-022 | `Procfile` (1) | `web: gunicorn … STATZWeb.wsgi` | NEEDS HUMAN DECISION | not referenced | 2025-09-22 | W: Azure startup command is `startup.sh`. Can't prove Oryx ignores it. | ASK |
| FILE-023 | `MEMORY.md` (root, 6) | assistant memory index stub | NEEDS HUMAN DECISION | not app code | 2026-07-17 | Doc: assistant layer (`About Me/`) | KEEP |
| FILE-024 | `scripts/set_production_version.py` (153) + `scripts/azure-deployment-version.yml` (39) | Azure DevOps step | NEEDS HUMAN DECISION | PATH: only the `.yml` (`scriptPath`); the `.yml` is not in `.github/` | 2025-10-21 | W: can't see Azure DevOps pipelines from the repo | ASK |
| FILE-025 | `arcade/wordlists/build_wordlist.py`, `_fetch_sources.py` | wordlist build tools | UNWIRED BY DESIGN / RECENT | IMP=0 (run manually) | 2026-08-17 | ALL | KEEP |
| FILE-026 | `contracts/migrations/remove_old_payment_history.py` (20) | unnumbered migration file | REVIEW ONLY - DB-COUPLED | in `migrations/` | 2025-04-21 | Decision 5 | KEEP |
| FILE-027 | `dibbs/db_objects.py` | `add_url_defaults`, `create_competitor_stats_index`, … | LIVE BY INDIRECTION | imported by `dibbs/migrations/0001_initial.py` and one test | 2026-09-25 | migration import | KEEP |
| FILE-028 | `.deployment` | `SCMPackaged=true` | LIVE BY INDIRECTION | Kudu config file, not referenced in-repo by design | 2025-10-06 | W: read by Azure Kudu | KEEP |
| FILE-029 | `webjobs/*.zip` (4) | packaged WebJobs | LIVE BY INDIRECTION | same names as the `run.sh` WebJob folders | 2025-10 – 2026-09 | W; nightly WebJob scripts are off limits | KEEP |

---

## 5. Unreferenced functions, classes, constants, forms (A3.3)

The scan covered every top-level `def`, `class` and UPPER_CASE constant in non-test, non-migration modules where WB(name) found nothing in another code file and at most one occurrence in its own file. It returned 156 hits. Not findings and dropped: settings constants (read by Django), `@admin.register` classes (G), `AppConfig` classes (S), `@receiver` functions (G), registered template tags (handled in §9), and `dibbs/db_objects.py` (migration).

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| FUNC-001 | `contracts/views/finance_views.py:33-39` | `safe_float` | CONFIRMED DEAD | WB(`safe_float`)=0 outside def | 2025-03-28 | ALL; pickaxe: 0 callers | REMOVE |
| FUNC-002 | `core/views.py:192-194` | `_solicitation_line_filter` | UNWIRED BY DESIGN / RECENT | WB=0 | 2026-09-16 (`2cec6a6`) | ALL | KEEP |
| FUNC-003 | `products/views.py:99-106` | `_resolve_canonical_nsn_queryset` | PROBABLY DEAD | WB=0 | 2026-07-09 | ALL; pickaxe: 1 (added only) | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-004 | `suppliers/views.py:1092-1109` | `_validate_contact_ids_for_supplier` | PROBABLY DEAD | WB=0 | 2026-04-22; pickaxe: last caller removed in `2a62b17` (2026-06-30) | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-005 | `contracts/services/sharepoint_service.py:100-107` | `build_default_path` | PROBABLY DEAD | WB=0 | 2026-04-24 (file 2026-10-12) | ALL; Doc: the DFAS AGENTS rule bans root-fallback paths, so nothing should start using it | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-006 | `contracts/services/folder_review/actions.py:20-33` | `_folder_in_latest_run` | UNWIRED BY DESIGN / RECENT | WB=0 | 2026-10-08 (Folder Review) | ALL; Doc: Folder Review Stage A/B | KEEP |
| FUNC-007 | `contracts/services/folder_scan/graph_walker.py:20` | `_CHILDREN_SELECT` | UNWIRED BY DESIGN / RECENT | WB=0 | 2026-10-01 | ALL | KEEP |
| FUNC-008 | `contracts/services/dfas_import.py:436-446` | `finalize_import_batch` | PROBABLY DEAD | WB=0 code, 1 doc | 2026-07-02 | ALL; Doc: CONTEXT_contracts.md:82 lists it as a "wrapper" (stale) | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-009 | `contracts/utils/contracts_schema.py:47-222` | `generate_contracts_schema_description` | PROBABLY DEAD | WB=0 code; `reports/views.py:16` imports only `generate_db_schema_snapshot` | 2026-06-30 | ALL | REMOVE (the only recent touch is a sweep commit; reports uses the sibling function). Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-010 | `contracts/utils/contracts_schema.py:224-315` | `generate_condensed_contracts_schema` | CONFIRMED DEAD | WB=0 code, 1 doc (`reports/docs/design.md`) | 2025-05-28 | ALL | REMOVE |
| FUNC-011 | `dibbs/services/awdrecs_parser.py:151-153` | `_span_text` | PROBABLY DEAD | WB=0 | 2026-06-02 | ALL; module used by the `poll_we_won_today` heartbeat task, not a nightly WebJob | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-012 | `dibbs/services/dibbs_awards_scraper.py:119-135` | `get_available_dates` | PROBABLY DEAD | WB=0 | 2026-03-27 | ALL; W: module on the `run-scrape-awards` path | ASK |
| FUNC-013 | `dibbs/services/dibbs_awards_scraper.py:138-156` | `get_dates_needing_scrape` | UNWIRED BY DESIGN / RECENT | WB=0 | 2026-09-25 | ALL | KEEP |
| FUNC-014 | `dibbs/services/dibbs_pdf.py:168` | `SECTION_D_START_RE` | PROBABLY DEAD | WB=0 | 2026-03-30 | ALL; W: `run-auto-import-dibbs` / `fetch_pending_pdfs` path | ASK |
| FUNC-015 | `dibbs/services/parser.py:65,68,71` | `SDVOSB_CODES`, `SMALL_BUSINESS_CODES`, `UNRESTRICTED_CODES` | PROBABLY DEAD | WB=0 each | 2026-03-10 | ALL; W: `auto_import_dibbs` path | ASK |
| FUNC-016 | `intake/matchers.py:69` | `MATCH_TYPES` | PROBABLY DEAD | WB=0 | 2026-05-19 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-017 | `intake/pdf_parser.py:185-192` | `_RE_INSPECTION_SUPPLIES_CAGE`, `_RE_INSPECTION_PACKAGING_CAGE` | PROBABLY DEAD | WB=0 each; pickaxe: last use removed in `2abaa85` (processing decommission) | 2026-05-26 | ALL; W: `intake.pdf_parser` is imported by `competitor_supplier_intel`, which `scrape_awards` reaches | ASK |
| FUNC-018 | `quote/services/bids.py:78-83` | `LINE_FIELDS` | UNWIRED BY DESIGN / RECENT | WB=0 | 2026-09-27 | ALL | KEEP |
| FUNC-019 | `suppliers/portal/serializers.py:31` | `ADDRESS_MODEL_TO_API` | PROBABLY DEAD | WB=0 | 2026-07-20 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-020 | `transactions/field_types.py:16` | `WIDGET_FOREIGN_KEY` | PROBABLY DEAD | WB=0 (callers use `WIDGET_SELECT`, same value) | 2026-02-12 | ALL | ASK (it's part of a widget-constant set; removing one alone is cosmetic) |
| FUNC-021 | `users/sharepoint_services.py:854-1099` (246) | `_DEFAULT_DOCS_PATH`, `_get_drive_id`, `_check_path_exists`, `_create_folder`, `ensure_contract_folder`, `upload_award_pdf_to_sharepoint`, `check_contract_sharepoint_status`, `build_queue_contract_pdf_path`, `download_award_pdf_bytes` | PROBABLY DEAD | WB=0 outside this block for all 9 names (`contracts/services/sharepoint_service.py` has its own `_get_drive_id`); every function takes a `queue_contract` (`processing.QueueContract`) | 2026-05-05 | ALL; pickaxe(`ensure_contract_folder`, `download_award_pdf_bytes`): last callers removed in `2abaa85` (2026-08-20, processing decommission) | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-022 | `users/forms.py:57-60` | `AnnouncementForm` | CONFIRMED DEAD | WB=0 code | 2025-10-15 | ALL | REMOVE |
| FUNC-023 | `contracts/forms.py:264-267` | `ContractCloseForm` | PROBABLY DEAD | WB=0 code, 8 doc. `ContractCloseView` is a `DetailView` with no form (`contract_views.py:306`) | 2026-04-23 | ALL; Doc stale: contracts AGENTS/CONTEXT/README/"Contracts Application.md" | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| FUNC-024 | `contracts/forms.py:446-454` | `ContractCancelForm` | CONFIRMED DEAD | WB=0 code, 6 doc. `ContractCancelView` doesn't use it | 2025-05-01 | ALL | REMOVE |
| FUNC-025 | `arcade/puzzles/art_pack.py:458-460` | `pack_load_count` (test-only) | UNWIRED BY DESIGN / RECENT | WB: 0 code, 2 test (`test_nonogram.py`) | 2026-08-17 | ALL; Tst | KEEP |
| FUNC-026 | `arcade/registry.py:23-24` | `get_enabled_games` (test-only) | UNWIRED BY DESIGN / RECENT | WB: 0 code, 4 test | 2026-08-17 | ALL; Tst; AGENTS.md forbids touching puzzle code | KEEP |
| FUNC-027 | `contracts/services/due_status.py:190-204` | `partition_clin_late_status` (test-only) | UNWIRED BY DESIGN / RECENT | WB: 0 code, 3 test | 2026-08-21 | ALL; Tst | KEEP |
| FUNC-028 | `dibbs/services/awards_file_importer.py:188-194` | `is_dibbs_mod_record` (test-only) | PROBABLY DEAD | WB: 0 code, 4 test (`test_contract_mods.py`) | 2026-06-29 | ALL; W: nightly import path | ASK |
| FUNC-029 | `quote/services/quotes.py:543-549` | `uncovered_lines` (test-only) | UNWIRED BY DESIGN / RECENT | WB: 0 code, 4 test | 2026-09-29 | ALL; Tst | KEEP |
| FUNC-030 | `quote/signals.py:7-12` | `on_dibbs_import_completed` | LIVE BY INDIRECTION | WB=0, but `@receiver(import_completed)` is connected in `quote/apps.py:10` | 2026-09-25 | G | KEEP |

`contracts/views/supplier_views.py:362-366` has five unused locals (flake8 F841). They're listed under IMPORT-003. They're lazy querysets, so they never actually run a query.

---

## 6. Orphan templates (A3.4)

PATH(rel) found no code reference for 47 template files. 21 of those are LIVE BY INDIRECTION and listed as single rows (TPL-018..020). The rest:

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| TPL-001 | `contracts/templates/contracts/dfas_contract_matcher_modal.html` (36) | DFAS matcher modal | PROBABLY DEAD | PATH(`contracts/dfas_contract_matcher_modal.html`)=0 code; basename=0 code; `dfas_import_review.html` uses inline modals | 2026-05-12 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-002 | `contracts/templates/contracts/includes/log_payment_modal.html` (143) | Finance Audit "Slice 2C" (retired) | PROBABLY DEAD | PATH=0 code; `{% include` of basename = 0 | 2026-05-18 | ALL; Doc: AGENTS_contracts.md (stale) | REMOVE with STATIC-001. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-003 | `contracts/templates/contracts/partials/contract_splits.html` (9) | comment-only stub | PROBABLY DEAD | PATH=0 code | 2026-04-24 | ALL; Doc: AGENTS/CONTEXT_contracts (stale) | REMOVE with TPL-004. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-004 | `contracts/templates/contracts/partials/contract_splits_README.md` (233) | README for TPL-003 | PROBABLY DEAD | describes TPL-003 only | 2026-04-16 | Doc | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-005 | `inventory/templates/inventory/delete_form.html` (21) | whole file | CONFIRMED DEAD | PATH=0 code; inventory docs say "orphaned, no view renders it" | 2025-04-29 | ALL | REMOVE |
| TPL-006 | `reports/templates/reports/admin_dashboard.html` (215) | pre-rebuild reports page | PROBABLY DEAD | PATH(`reports/admin_dashboard.html`)=0 code; 3 doc (PROJECT_AGENTS.md:111, AGENTS_suppliers.md:153,222, both stale) | 2026-04-23 | ALL | REMOVE; drop the stale doc mentions. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-007 | `reports/templates/reports/request_form.html` (14) | whole file | PROBABLY DEAD | PATH=0 code (`request_form` in `hub.html` is a context var) | 2025-10-29 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-008 | `reports/templates/reports/user_dashboard.html` (86) | replaced by `hub.html` | PROBABLY DEAD | PATH=0 code | 2026-04-23 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-009 | `templates/add_announcement.html` (26) | whole file | PROBABLY DEAD | PATH=0 code; `add_announcement` view returns `JsonResponse`; **extends non-existent `base.html`** | 2026-04-22 (sweep `915aea8`) | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-010 | `templates/delete_announcement.html` (29) | whole file | PROBABLY DEAD | same as TPL-009 | 2026-04-22 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-011 | `templates/suppliers/includes/status_toggle.html` (16) | whole file | PROBABLY DEAD | PATH=0 code; `supplier_edit.html` uses `toggle_switch.html` | 2025-12-19 | ALL; Doc: docs/template_tracking.md | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-012 | `training/templates/training/manage_matrix_success.html` (8) | whole file | CONFIRMED DEAD | PATH=0 code; `manage_matrix` redirects | 2025-05-08 | ALL | REMOVE |
| TPL-013 | `users/templates/tailwind/**` (30 files, 262 LOC) | crispy-forms "tailwind" template pack | CONFIRMED DEAD | `CRISPY_ALLOWED_TEMPLATE_PACKS = CRISPY_TEMPLATE_PACK = "bootstrap5"` (`settings.py:338-339`); `git grep tailwind` in .py/.html outside this folder = 0, apart from CDN `<script>` lines and a test asserting **no** tailwind; files reference only each other | 2025-02-11 | ALL; G: crispy pack resolution | REMOVE, with TPL-014 |
| TPL-014 | `users/templatetags/tailwind_filters.py` (16) | `tailwind_field`, `tailwind_label` | CONFIRMED DEAD | `{% load tailwind_filters %}` sites = 1 (`users/templates/tailwind/field.html`, inside TPL-013) | 2025-02-11 | G | REMOVE |
| TPL-015 | `users/templates/users/register.html` (64) | whole file | CONFIRMED DEAD | PATH=0 code; `register()` redirects to Microsoft (`users/views.py:352-355`) | 2025-04-29 | ALL; Doc: AGENTS_users.md:169 "is never rendered" | REMOVE |
| TPL-016 | `users/templates/users/manage_settings.html` (431) | whole file | PROBABLY DEAD | only renderer is VIEW-003 (unrouted); reverses non-existent URL names | 2025-12-31 | ALL | REMOVE with VIEW-003. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-017 | `users/templates/users/settings_view.html` (119) | whole file | PROBABLY DEAD | only renderer is URL-001; TemplateSyntaxError | 2026-04-22 | ALL | REMOVE with URL-001. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| TPL-018 | `quote/templates/quote/research/_panel_{approved,awards,sam,sols,status}.html` | whole file | LIVE BY INDIRECTION | PATH=0 literal | 2026-10-05 | D: `render(request, f'quote/research/_panel_{panel}.html')` (`quote/research_views.py:92`) | KEEP |
| TPL-019 | `templates/arcade/{lights_out,nonogram,wordle}.html` | whole file | LIVE BY INDIRECTION | PATH=0 literal | 2026-08-17 | D: `f"arcade/{game_key}.html"` (`arcade/views.py:101`) | KEEP |
| TPL-020 | `users/templates/admin/users/apppermission/change_form.html` | whole file | LIVE BY INDIRECTION | PATH=0 literal | 2025-02-27 | G: Django admin template override convention | KEEP |

Dependent templates of ASK URL rows aren't separate findings: `contracts/clin_acknowledgment_form.html` (URL-012) and `contracts/admin_tools.html` (URL-028).

---

## 7. Orphan static assets, vendored libraries, CDN (A3.5)

PATH(rel) and basename found no code reference for any first-party asset below. Marauder ES modules (`arcade/static/arcade/js/marauder/*.js`) are LIVE: they're imported relatively from `main.js`, which shows up as basename hits.

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| STATIC-001 | `contracts/static/contracts/js/log_payment_modal.js` (382) | whole file | PROBABLY DEAD | PATH(`contracts/js/log_payment_modal.js`)=0 code; WB(`logPaymentModal`)=0 outside file | 2026-05-19 | ALL | REMOVE with TPL-002. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| STATIC-002 | `contracts/static/js/supplier_modal.js` (171) | odd path `static/js/` | PROBABLY DEAD | PATH(`js/supplier_modal.js`)=0 code; `{% static` of it = 0 | 2025-10-24 | ALL; Doc: contracts AGENTS/CONTEXT, release note 2026-05-18 (historical) | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| STATIC-003 | `contracts/static/contracts/images/nist.png` (18 KB) | whole file | CONFIRMED DEAD | PATH(`nist.png`)=0 | 2025-04-23 | ALL | REMOVE |
| STATIC-004 | `static/certificates/server.crt` (23) | whole file | CONFIRMED DEAD | PATH(`certificates/server.crt`, `server.crt`)=0 code; the cert-download views are gone (`download_cert`/`cert_error` = 0) | 2025-04-29 | ALL | REMOVE |
| STATIC-005 | `static/videos/cert_install.mp4` (3.7 MB) | whole file | CONFIRMED DEAD | PATH(`cert_install`)=0 | 2025-04-29 | ALL | REMOVE |
| STATIC-006 | `static/images/screenshots/cert-install.png` (154 KB), `static/images/screenshots/desktop-1.png` (144 KB) | whole file | CONFIRMED DEAD | PATH=0; `static/manifest.json:53-80` lists `desktop-landing`, `desktop-dashboard`, `mobile-*` only | 2025-04-29 / 2025-04-24 | ALL | REMOVE both |
| STATIC-007 | `static/images/float.png` (70 KB) | whole file | CONFIRMED DEAD | PATH(`float.png`)=0 | 2025-04-23 | ALL | REMOVE |
| STATIC-008 | `static/images/gears-metal-stainless-technology.jpg` (759 KB) | whole file | PROBABLY DEAD | PATH(`gears-metal`)=0 (incl. CSS `url()`) | 2026-06-26 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| STATIC-009 | `users/static/images/gears-metal-stainless-technology.jpg` (2.2 MB, different bytes, same collected path) | whole file | CONFIRMED DEAD | PATH=0; also shadowed by STATIC-008 at `collectstatic` | 2025-04-23 | ALL | REMOVE |
| STATIC-010 | `static/contracts/letter_templates/Purchase_Order_Acknowledge_Letter1.htm` + `_files/` (9 files, 4,205 text lines, 310 KB) | Word "Save as HTML" export | CONFIRMED DEAD | PATH(`letter_templates`, `Acknowledge_Letter1`)=0 code | 2025-04-23 | ALL | REMOVE |
| STATIC-011 | `static/css/css.zip` (12.7 KB) | whole file | PROBABLY DEAD | PATH=0 code | 2025-12-18 | ALL | REMOVE. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| STATIC-012 | `static/inventory/morth.css` (12,805) | Bootswatch dump | CONFIRMED DEAD | PATH(`morth.css`)=0 code | 2025-04-23 | ALL | REMOVE |
| STATIC-013 | `static/inventory/sandstone.css` (12,190) | Bootswatch dump | CONFIRMED DEAD | PATH(`sandstone.css`)=0 code | 2025-04-23 | ALL | REMOVE |
| STATIC-014 | `static/js/portal_dashboard.js` (491) | whole file | PROBABLY DEAD | PATH=0 code; reads `#portal-context-data` + `window.portalDashboardConfig`, neither defined anywhere | 2025-10-31 | ALL | REMOVE with URL-004. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| STATIC-015 | `static/suppliers/js/supplier_enrich.js` (132) | whole file | PROBABLY DEAD | PATH(`suppliers/js/supplier_enrich.js`)=0 code; `supplier_enrich.html` uses inline `<script>` | 2025-12-04 | ALL; Doc: AGENTS/CONTEXT_suppliers say "bundled" (stale) | REMOVE; fix the docs. Doubt is age only (last touched 3–12 months ago); zero references after all A2 checks. |
| STATIC-016 | `arcade/static/arcade/js/marauder/__selftest__.html` | dev self-test harness | UNWIRED BY DESIGN / RECENT | documented in CONTEXT_arcade.md | 2026-08-19 | Doc | KEEP |
| STATIC-017 | `static/admin/**` (127 files, 1.46 MB) and `static/django-browser-reload/**` (2) | committed copies of third-party static (also contains custom `static/admin/js/app_permissions.js`, loaded by `users/admin.py` `Media`) | NEEDS HUMAN DECISION | Django serves these from the packages; the copies in `STATICFILES_DIRS` override them | 2025-04-23 | S; G | ASK (would need a careful split from `app_permissions.js`) |
| STATIC-018 | 21 templates, 36 CDN refs: `templates/base_template.html:57-60` (jQuery 3.6.0, jQuery UI 1.12.1, Bootstrap 5.3.3, Bootstrap Icons), `users/templates/users/base_no.html:13,14,142`, `contracts/…/contract_management.html:6,1229` (Quill), `mailer/…/campaign_form.html:7,111` + `campaign_followup_form.html:7,96` (Quill), `contracts/…/folder_tracking.html:532` (htmx via unpkg), `intake/…/draft_queue.html:9` (**`@tabler/icons-webfont@latest`**), `intake/…/email_compose.html:7,8,206`, `transactions/…/transaction_modal.html:2,3` (tom-select@2), `contracts/…/contacts/address_{form,selector,create_success}.html` (`cdn.tailwindcss.com`), `contracts/…/notes_popup_base.html:7,17`, `reminders_popup_base.html:7,31`, `documents_browser.html:600`, `contract_{cancel,close,reopen,detail}.html:5/10`, `templates/suppliers/status_report.html:7`, `templates/system_test.html:10` | CDN references (forbidden by project rule) | NEEDS HUMAN DECISION | `git grep -noE "(src\|href)=[\"']https?://[^\"']*(cdn\|unpkg\|jsdelivr\|cloudflare\|googleapis\|bootstrapcdn\|jquery\|fontawesome\|gstatic)"` → 36 hits / 21 files | `base_template.html` 2026-10-09; others vary | Doc: project no-CDN rule | ASK (not dead code; fixing means vendoring, out of scope) |

**Vendored third-party libraries never loaded:** none. `static/js/vendor/chart.umd.min.js` is loaded by `products/nsn_detail.html:439` and `training/dashboard.html:117`. `chartjs-adapter-date-fns.bundle.min.js` is loaded by `nsn_detail.html:440`. `static/css/spacelab.min.css` is loaded by `base_template.html:63`, `base_no.html:9` and `documents_browser.html:17`.

---

## 8. Management commands (A3.6)

All 44 commands were classified. `WB(name)` was searched in WebJob scripts, `startup.sh`, workflows, docs, `call_command`, other commands, templates (UI "run this" hints), and `.claude/settings.local.json`.

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| CMD-001 | 25 commands | **LIVE**: `run_background_tasks`, `process_contract_log_exports`, `auto_import_dibbs`, `fetch_pending_pdfs`, `scrape_awards` (WebJobs); `set_build_info`, `import_release_notes`, `verify_stored_procs` (`startup.sh`); `scan_folders`, `fix_folder_paths` (`folder_scan/status.html`); `scan_inbox` (`base_template.html`, tools templates); `clear_stale_locks` (`intake/admin.py`); `discover_sharepoint_ids` (`settings.py`, `sharepoint_services`); `dfas_receipts_backfill` (CONTEXT.md); `initialize_sequence_numbers`, `update_app_registry`, `backfill_nsn_normalized`, `list_unnormalized_nsns`, `seed_quote_demo`, `arcade_verify_art`, `backfill_award_ledger`, `purge_stale_award_staging`, `run_competitor_supplier_backfill`, `scan_inbox_probe`, `folder_review_move_closed` (docs / tests / runbooks) | LIVE BY INDIRECTION | WB(name) ≥ 1 in W or Doc or code for each | 2025-03-04 – 2026-10-12 | W, Doc | KEEP |
| CMD-002 | `contracts/management/commands/probe_folder_delta.py` (360) | whole file | UNWIRED BY DESIGN / RECENT | WB: 2 test | 2026-10-01 | Tst | KEEP |
| CMD-003 | `users/management/commands/check_clin_tables.py`, `check_contract_table.py` | ONE-TIME (pre-migration table checks) | UNWIRED BY DESIGN / RECENT | WB: doc only | 2026-08-21 (touched by `a89b8c9`) | Doc | KEEP (90-day rule); re-check later |
| CMD-004 | `arcade/management/commands/arcade_close_stale_attempts.py` | whole file | UNWIRED BY DESIGN / RECENT | WB: 2 doc (`nonogram_phase_a_findings.md`) | 2026-08-17 | Doc | KEEP |
| CMD-005 | `users/management/commands/fix_appregistry.py`, `fix_apppermissions.py`, `cleanup_permissions.py`, `cleanup_app_permissions.py` | ONE-TIME (Feb-2025 AppRegistry/AppPermission repairs) | NEEDS HUMAN DECISION | WB: doc only (users AGENTS/CONTEXT) | 2025-02-27 | ALL | ASK |
| CMD-006 | `users/management/commands/migrate_notes.py`, `get_content_types.py` | ONE-TIME (ClinNote/ContractNote → Note migration, Feb 2025) | NEEDS HUMAN DECISION | WB: doc only | 2025-02-28 | ALL | ASK |
| CMD-007 | `contracts/management/commands/refresh_nsn_view.py` (40) | ONE-TIME; help text says "This command is deprecated" | NEEDS HUMAN DECISION | WB: doc only | 2025-03-13 | ALL | ASK |
| CMD-008 | `users/management/commands/add_test_permissions.py`, `set_default_passwords.py`, `set_user_password.py`, `update_site.py` | UNREFERENCED (user/permission utilities) | NEEDS HUMAN DECISION | WB=0 everywhere | 2025-02-27 – 2025-10-15 | ALL; may be run by hand over SSH | ASK (`set_default_passwords` is security-sensitive with Microsoft-only login) |
| CMD-009 | `STATZWeb/management/commands/check_security.py`, `export_database.py`, `runserver_custom.py`, `show_version.py` | UNREFERENCED (dev/ops utilities) | NEEDS HUMAN DECISION | WB=0 everywhere | 2025-04-03 – 2025-10-15 | ALL | ASK |

CMD-001 is one grouped row. CMD-003, 005, 006, 008 and 009 each cover a group of files.

---

## 9. Template tags, context processors, middleware, signals (A3.7)

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| TAG-001 | `dibbs/templatetags/dibbs_extras.py:31-34` | filter `normalize_cage` | UNWIRED BY DESIGN / RECENT | `\|\s*normalize_cage` / `{% normalize_cage` in templates = 0 | 2026-09-25 | G | KEEP |
| TAG-002 | `users/templatetags/custom_tags.py:7-9` | tag `get_database_name` | CONFIRMED DEAD | template usage = 0 (the library is loaded by 4 templates for other tags) | 2025-02-14 | G; pickaxe: 0 users | REMOVE (the function only) |
| MISC-001 | 10 custom context processors (`settings.py:159-184`) | all registered | LIVE BY INDIRECTION | each dotted path is in `TEMPLATES.context_processors` | 2026-09-25 | S | KEEP |
| MISC-003 | `contracts/signals.py` | empty stub | LIVE BY INDIRECTION | imported by `contracts/apps.py:10` `ready()` | 2025-04-03 | G | KEEP |
| MISC-002 | `transactions/signals.py`, `users/signals.py`, `quote/signals.py`, `dibbs/signals.py` | receivers + signal defs | LIVE BY INDIRECTION | imported in `ready()` (`transactions`, `users`, `quote`); `dibbs.signals.import_completed` imported by `quote.signals` | 2025-04-03 – 2026-09-25 | G | KEEP |

All 12 template-tag libraries have at least one `{% load %}` site. Only the two tags above are registered but never used.

---

## 10. Commented-out code, `if False:`, unreachable code (A3.8)

- Python comment runs of ≥10 lines that are ≥60% code-like: **0**.
- `if False:` / `if 0:`: **0**.
- Statements after an unconditional `return` / `raise` / `continue` / `break` in the same block (AST): **0**.
- HTML/JS comment blocks of ≥10 lines that look like code: 5. Four are JS doc headers (`match_modal.js`, `capabilities.js`, `packhouse.js`, `quote-drawer.js`) and are not dead. The fifth is below.

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| COMMENT-001 | `templates/suppliers/supplier_edit.html:125-196` | 72-line `<!-- CHANGE TRACKING … TESTING GUIDE -->` sent to every browser | PROBABLY DEAD | `<!--(.*?)-->` spanning ≥10 lines: 1 non-doc block repo-wide; no JS reads HTML comments (`git grep -n "COMMENT_NODE\|nodeType === 8"` = 0) | 2025-12-31 | ALL (D: no comment-node parsing) | REMOVE (doubt is age only; it's prose, not code) |

---

## 11. Unused imports / variables (A3.8, flake8 read-only, grouped)

Command: `python -m flake8 --select=F401,F841 --exclude=.git,.venv,_extra,node_modules,staticfiles,media,migrations,scratch .`. Result: **370** (F401 = 337, F841 = 33).

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| IMPORT-001 | `contracts/views/__init__.py` | 132 F401 (re-export hub) | LIVE BY INDIRECTION | `urls.py` reaches views through `views.X` / `from .views import …` | 2026-10-12 | L | KEEP. Remove individual names only together with an approved URL/VIEW row. |
| IMPORT-002 | ~80 non-test modules, ≈ 190 F401 (full list: re-run the command above). Top: `contracts/views/supplier_views.py` 12, `users/views.py` 10, `contracts/views/contract_log_views.py` 9, `suppliers/views.py` 6, `contracts/views/folder_tracking_views.py` 6, `contracts/forms.py` 6, `contracts/views/contract_views.py` 5, `contracts/views/contacts_views.py` 5, `accesslog/views.py` 5, `users/ms_views.py` 4, `mailer/forms.py` 4 | unused imports | NEEDS HUMAN DECISION | flake8 F401 | per line; files span 2025-02 → 2026-10 | L, G: some imports exist for side effects (signals, admin registration) | ASK (mechanical cleanup, but it touches many live modules; better as its own PR) |
| IMPORT-003 | 26 F841 in non-test code, e.g. `contracts/views/supplier_views.py:362-366` (5), `contracts/views/dashboard_views.py:259`, `intake/views.py:573,681`, `products/views.py:782`, `reports/services/notifications.py:121`, `tools/services/scan_inbox_graph.py:210`, `users/forms.py:254` | unused local variables in live functions | NEEDS HUMAN DECISION | flake8 F841 | per line; several inside RECENT files (`intake/views.py`, `tools/services/scan_inbox_*`) | L | ASK (these are edits inside live functions, closer to refactoring than deletion) |
| IMPORT-004 | tests (`*/tests*`, `test_*.py`) | ≈ 46 F401/F841 | NEEDS HUMAN DECISION | flake8 F401/F841 restricted to test paths | per line | Tst | ASK |

---

## 12. SQL and script files (A3.9; report only, never deleted per Decision 5)

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| SQL-001 | `SQL/create_user_mapping.sql` | whole file | REVIEW ONLY - DB-COUPLED | WB(`create_user_mapping`)=0 | 2025-03-25 | Doc | KEEP |
| SQL-002 | `SQL/migrate_users.sql` | whole file | REVIEW ONLY - DB-COUPLED | WB=0 | 2025-03-26 | Doc | KEEP |
| SQL-003 | `SQL/fix_dibbs_award_mod_artifact.sql` | whole file | REVIEW ONLY - DB-COUPLED | WB=0 | 2026-06-29 | Doc | KEEP |
| SQL-004 | `SQL/migrate_data.sql` | whole file | REVIEW ONLY - DB-COUPLED | 3 doc (PROJECT_AGENTS, PROJECT_CONTEXT, products AGENTS) | 2026-08-21 | Doc | KEEP |
| SQL-005 | `contracts/sql/migrate_clin_fix_packaging_to_contract_level_charge.sql` | whole file | REVIEW ONLY - DB-COUPLED | 1 doc (AGENTS_contracts) | 2026-06-26 | Doc | KEEP |
| SQL-006 | `dibbs/sql/usp_process_award_staging.sql` | stored proc source | REVIEW ONLY - DB-COUPLED | code: `proc_verification.py`, `proc_versions.py`, `db_objects.py`, `awards_file_importer.py` + tests; `verify_stored_procs` at startup | 2026-09-25 | W | KEEP |
| SQL-007 | `scripts/fix_undashed_draft_contract_numbers.sql` | whole file | REVIEW ONLY - DB-COUPLED | 1 doc (CONTEXT_intake) | 2026-06-08 | Doc | KEEP |

No model, field, table, view or stored procedure was a deletion candidate. Models were not part of the symbol scan beyond confirming each has admin, query, FK or migration references.

---

## 13. Tests that only exercise flagged code (A3.10)

No test references any `REMOVE` item. Searched: every REMOVE symbol name, URL name and route literal in `*/tests/*`, `tests.py`, `test_*.py` → 0. The only tests whose target exists solely for them:

| ID | Path:line | Symbol/file | Tier | Evidence (exact search patterns run + hit counts) | Last touched | Indirection checks done | Proposed action |
|---|---|---|---|---|---|---|---|
| TEST-001 | `arcade/tests/test_nonogram.py` | tests `pack_load_count` (FUNC-025) | UNWIRED BY DESIGN / RECENT | WB=2 | 2026-08-17 | Tst | KEEP |
| TEST-002 | `arcade/tests/test_nonogram.py`, `test_puzzles.py` | tests `get_enabled_games` (FUNC-026) | UNWIRED BY DESIGN / RECENT | WB=4 | 2026-08-17 | Tst | KEEP |
| TEST-003 | `contracts/tests/test_due_status.py` | tests `partition_clin_late_status` (FUNC-027) | UNWIRED BY DESIGN / RECENT | WB=3 | 2026-08-21 | Tst | KEEP |
| TEST-004 | `dibbs/tests/test_contract_mods.py` | tests `is_dibbs_mod_record` (FUNC-028) | UNWIRED BY DESIGN / RECENT | WB=4 | file 2026-09-25 | Tst | KEEP (goes with FUNC-028 → ASK) |
| TEST-005 | `quote/tests/test_quote_manual.py` | tests `uncovered_lines` (FUNC-029) | UNWIRED BY DESIGN / RECENT | WB=4 | 2026-09-29 | Tst | KEEP |

---

## 14. Top CONFIRMED DEAD items by LOC

| # | ID | Item | LOC |
|---:|---|---|---:|
| 1 | STATIC-012 | `static/inventory/morth.css` | 12,805 |
| 2 | STATIC-013 | `static/inventory/sandstone.css` | 12,190 |
| 3 | STATIC-010 | `static/contracts/letter_templates/` (9 files, +310 KB) | 4,205 |
| 4 | TPL-013 | `users/templates/tailwind/` (30 files) | 262 |
| 5 | FUNC-010 | `generate_condensed_contracts_schema` | 92 |
| 6 | FILE-001 | `STATZWeb/pdf_security.py` | 86 |
| 7 | TPL-015 | `users/templates/users/register.html` | 64 |
| 8 | URL-002 | `users:settings-get` + `ajax_get_user_setting` | 49 |
| 9 | FILE-005 | `contracts/utils/image_processing.py` | 42 |
| 10 | VIEW-002 | `save_user_setting` | 34 |

By size, the largest CONFIRMED DEAD binary is `static/videos/cert_install.mp4` at 3.7 MB (STATIC-005).

---

## 15. Phase B notes (for when IDs are approved)

- Each approved URL row removes the `urls.py` line, the view (unless another route still uses it), the matching `contracts/views/__init__.py` import and `__all__` entries, and any template listed as a dependent. All of that goes in one commit per category.
- Docs to touch for removed items only: `users/CONTEXT_users.md`, `users/README.md`, `users/AGENTS_users.md`, `contracts/CONTEXT_contracts.md`, `contracts/AGENTS_contracts.md`, `contracts/utils/README-utils.md`, `suppliers/AGENTS_suppliers.md`, `suppliers/CONTEXT_suppliers.md`, `inventory/AGENTS_inventory.md`, `inventory/CONTEXT_inventory.md`, `transactions/CONTEXT_transactions.md`, `PROJECT_AGENTS.md:111`, `docs/template_tracking.md`.
- `makemigrations --check --dry-run` must use the scratch SQLite settings or CI settings, because the default shell environment points at the real dev SQL Server.
- Re-take the URL snapshot after each commit and diff it against `url_snapshot_before.txt`.
