# AGENTS.md — `reports` app

Read `reports/CONTEXT.md` first. This file adds safe-edit guidance for AI coding agents; it does not repeat the context file.

---

## 1. Purpose of This File

Defines how to safely modify the `reports` app. Every rule here is grounded in the actual code. This app is a **feature app** (reporting help-desk + AI admin workspace), not a core domain app.

---

## 2. App Scope

**Owns:**
- `ReportRequest` lifecycle: user submits → admin writes SQL → user runs/exports
- SQL safety enforcement (`utils.py`)
- OpenRouter AI streaming for SQL generation (admin only)
- Per-user AI model preference storage via `UserSettings`

**Does not own:**
- The `contracts_*` tables it queries — those belong to the `contracts` app
- OpenRouter model config globally — that belongs to `suppliers.openrouter_config`
- `UserSettings` — belongs to the `users` app
- The global nav and AI settings drawer — lives in `templates/base_template.html`

---

## 3. Read This Before Editing

### Before changing models
- `reports/models.py` — single model, UUID PK, status/category choices as string constants
- `reports/migrations/0001_initial.py` — only migration; no subsequent schema changes
- `reports/admin.py` — uses `status`, `category`, `created_at`, `last_run_at` directly
- `reports/forms.py` — `SQLUpdateForm` exposes `sql_query` and `context_notes` to admins

### Before changing views
- `reports/views.py` — all logic lives here; contains `CORE_TABLES` list at the top
- `reports/utils.py` — `is_safe_select`, `apply_limit`, `run_select` are called by multiple views
- `users/user_settings.py` — `UserSettings.get_setting` / `save_setting` called in `admin_dashboard` and `admin_save_ai_settings`
- `suppliers/openrouter_config.py` — `get_model_for_request`, `get_openrouter_model_info` called in views

### Before changing templates
- `reports/templates/reports/admin_dashboard.html` — contains substantial inline JS (SSE stream handling, form wiring, `fetch` to `suppliers:global_ai_model_config`)
- `templates/base_template.html` — uses `reports:my_requests` and `reports:admin_save_ai_settings` URL names; hosts the global AI settings form

### Before changing URL names
- Search `templates/base_template.html`, `reports/templates/reports/*.html`, and `reports/views.py` for any `reverse(...)` or `{% url '...' %}` referencing `reports:` names

### Before changing SQL safety logic
- `reports/utils.py` — `is_safe_select`, `apply_limit`, `run_select` are the only guard between user-visible SQL and the database; used by `run_report`, `export_report`, and `admin_preview_sql`

---

## 4. Local Architecture / Change Patterns

- All business logic lives in `reports/views.py`. There are no service modules, no selectors, no tasks. The `reports/services/` directory exists but is empty.
- `reports/utils.py` handles SQL validation and CSV serialization only — it is stateless and has no side effects.
- Templates are moderately thin on the user side but the admin template (`admin_dashboard.html`) contains a significant amount of JavaScript that drives the SSE stream, form auto-fill, and shared model config POST.
- No signals, no Celery tasks, no management commands.
- The `_is_admin` guard function in `views.py` (checks `user.is_superuser`) is the only permission helper; it is not shared with other apps.

---

## 5. Files That Commonly Need to Change Together

| Change | Files that must move together |
|---|---|
| Add a field to `ReportRequest` | `models.py` + new migration + `admin.py` (readonly_fields) + `forms.py` if admin-editable + relevant templates |
| Change status values (`pending`/`completed`/`change`) | `models.py` constants + all `views.py` references + templates that branch on status + `admin.py` list_filter |
| Change a URL name | `urls.py` + every `{% url 'reports:...' %}` in templates + any `reverse('reports:...')` in `views.py` |
| Add a new admin view | `views.py` + `urls.py` + `admin_dashboard.html` (or new template) |
| Change AI streaming behavior | `views.py` (`admin_ai_stream`) + `admin_dashboard.html` JS + possibly `suppliers/openrouter_config.py` |
| Change per-user AI settings keys | `views.py` (`reports_ai_model`, `reports_ai_fallbacks`) + `templates/base_template.html` hidden form fields |

---

## 6. Cross-App Dependency Warnings

### This app depends on:

- **`users` app** — `ReportRequest.user` FK to `AUTH_USER_MODEL`; `UserSettings.get_setting` / `save_setting` for AI model preferences keyed as `reports_ai_model` and `reports_ai_fallbacks`
- **`suppliers` app** — `suppliers.openrouter_config.get_openrouter_model_info` and `get_model_for_request` are called in `admin_dashboard` and `admin_ai_stream`; the admin template JS POSTs to `suppliers:global_ai_model_config` URL
- **`contracts` app (indirect)** — `CORE_TABLES` in `views.py` hardcodes 17 `contracts_*` table names used to build the AI schema prompt; if any of those tables are renamed or dropped in the `contracts` app, update `CORE_TABLES` or AI prompts will silently miss schema

### Other apps that depend on this app:

- **`templates/base_template.html`** — project-wide base template uses `reports:my_requests` (nav link) and `reports:admin_save_ai_settings` (AI settings form action); renaming these URL names breaks the global nav for all users
- No other app imports from `reports` in Python (confirmed by search)

---

## 7. Security / Permissions Rules

- **All views** are decorated with `@login_required`. Do not remove this.
- **Admin views** (`admin_dashboard`, `admin_save_sql`, `admin_delete_request`, `admin_preview_sql`, `admin_ai_stream`, `admin_save_ai_settings`) add `@user_passes_test(_is_admin)` which checks `user.is_superuser`. Do not weaken this to group-based checks without a security review.
- **Object-level ownership**: `run_report`, `export_report`, and `request_change` manually verify `rr.user_id == request.user.id or request.user.is_superuser`. If you add new views that access `ReportRequest` by PK, replicate this check.
- **SQL safety**: `is_safe_select` in `utils.py` is the only barrier between stored SQL and the database. Do not bypass it with direct `connection.cursor().execute()` calls in new views.
- **CSV export**: `export_report` streams up to 50,000 rows without pagination. Treat it as a sensitive download path; preserve the ownership check and the `run_select` call.
- **AI stream**: The SSE endpoint (`admin_ai_stream`) is superuser-only but accepts `prompt`, `model`, `extra`, and `full` query params from the client. Adding new params should be done carefully to avoid prompt injection or schema leakage.

---

## 8. Model and Schema Change Rules

- `ReportRequest` is the only model. It has a UUID PK — do not change to integer without a data migration.
- Status values are string constants (`STATUS_PENDING = "pending"`, etc.) defined on the model class and referenced by string in `views.py` filter calls. If you add or rename a status, update: `models.py` choices, all `views.py` filter/branch logic, and any template `{% if rr.status == "..." %}` checks.
- `ai_prompt` and `ai_result` fields exist on the model but are never populated by any current view. Do not remove them without checking for future use or data already stored.
- Only one migration exists (`0001_initial.py`). New field additions require a new migration. Coordinate with `startup.sh` if `RESET_REPORTS=1` is used in staging — that fake-resets migrations.
- `last_run_at` and `last_run_rowcount` are updated via `update_fields` in `run_report`. If you add audit fields, follow the same targeted-save pattern.

---

## 9. View / URL / Template Change Rules

- URL names `reports:my_requests` and `reports:admin_save_ai_settings` are used in `templates/base_template.html` (project-wide). Renaming them breaks all pages. Search globally before touching.
- `admin_preview_sql` re-renders `reports/admin_dashboard.html` with extra context keys `preview_columns` / `preview_rows`. If you refactor the admin template, preserve these keys.
- The admin template passes `global_ai_model_info_json` (a JSON-serialized dict from `get_openrouter_model_info()`) into an inline `<script>` block. If you rename or restructure that dict, the JS in `admin_dashboard.html` will break silently.
- `admin_dashboard` passes `pending` as a queryset of `ReportRequest` objects filtered to `status__in=[STATUS_PENDING, STATUS_CHANGE]`. Templates iterate this directly — changing the variable name requires a template update.
- The JS in `admin_dashboard.html` references DOM IDs tied to `SQLUpdateForm` field names (`id_sql_query`, `id_context_notes`). Renaming those form fields breaks the copy-from-AI flow.

---

## 10. Forms / Serializers / Input Validation Rules

- `ReportRequestForm` intentionally exposes only `title`, `description`, `category` — never `sql_query`, `status`, or `user`. Do not add fields that let users set their own status or inject SQL.
- `SQLUpdateForm` exposes `sql_query` and `context_notes` for admins only. If you add fields here, confirm the view passes the right `instance` and that `admin_save_sql` saves them correctly.
- All SQL execution goes through `utils.run_select` → `utils.is_safe_select` → `utils.apply_limit`. Do not accept raw SQL from user-facing forms or views.
- `request_change` appends a timestamped string to `context_notes` using string concatenation. If you change this format, existing notes remain in the old format — handle gracefully.

---

## 11. Background Tasks / Signals / Automation Rules

**None.** There are no signals, no Celery tasks, no cron jobs, and no management commands in this app.

The only "async" behavior is the SSE stream in `admin_ai_stream`, which is synchronous from Django's perspective — it holds an open HTTP connection while iterating OpenRouter's streaming response. It does not use Django Channels or background workers.

---

## 12. Testing and Verification Expectations

**There are no real tests.** `reports/tests.py` contains only the autogenerated `TestCase` stub.

After making changes, manually verify:

1. **User flow**: log in as a non-superuser → visit `/reports/` → submit a new request → confirm it appears as pending
2. **Admin flow**: log in as superuser → `/reports/admin/` → select a pending request → paste SQL → Preview → Save → confirm status becomes Completed
3. **Run/Export**: as the owning user → click Run on a completed report → confirm results render → click Export CSV → confirm file downloads
4. **Change request**: as owner → click Request Changes on a completed report → confirm status flips to `change`
5. **AI stream**: open admin workspace → enter a prompt → confirm SSE tokens arrive and the SQL copies into the editor
6. **Permission wall**: log in as non-superuser → attempt `/reports/admin/` → confirm redirect (not 200)
7. **Base template**: confirm the `Reports` nav link and AI settings form still render on any page after URL changes

---

## 13. Known Footguns

- **`CORE_TABLES` is a hardcoded list of `contracts_*` table names** at the top of `views.py`. If any `contracts` app table is renamed, the AI schema prompt silently drops that table. There is no runtime warning.
- **URL names in `base_template.html`**: `reports:my_requests` and `reports:admin_save_ai_settings` are baked into the project-wide base template. Renaming these without a global search will cause `NoReverseMatch` errors site-wide.
- **JS form ID coupling**: `admin_dashboard.html` uses `document.getElementById('id_sql_query')` (Django's default field ID format). If `SQLUpdateForm` field names change, the copy-from-AI button silently stops working.
- **`admin_ai_stream` POSTs to `suppliers:global_ai_model_config`** from client-side JS. If that suppliers URL is removed or renamed, the model-save button in the admin panel fails with a 404 — no Python error, JS console only.
- **Status string constants**: Views filter by `status__in=[ReportRequest.STATUS_PENDING, ReportRequest.STATUS_CHANGE]`. Adding a new status without updating every queryset filter will cause requests to disappear from the admin list.
- **`ai_prompt` / `ai_result` fields are never written**: they exist in the model/DB but no view populates them. Do not rely on them for data; do not remove them without checking for any future migration or external writes.
- **`export_report` does not stream**: it calls `run_select(limit=50000)` and holds the full result in memory before writing CSV. Very large result sets will cause memory pressure.
- **No test coverage**: any refactor of `utils.py` SQL safety logic carries silent regression risk.

---

## 14. Safe Change Workflow

1. Read `reports/CONTEXT.md` for the big picture
2. Read the specific files involved (model, view, template, form as applicable)
3. Search `templates/base_template.html` and all `reports/templates/` for URL name and context key references
4. If touching `CORE_TABLES` or SQL paths, also check `reports/utils.py` end-to-end
5. If touching AI settings keys (`reports_ai_model`, `reports_ai_fallbacks`), also check `users/user_settings.py` for the storage API
6. If touching the admin template JS, trace the DOM IDs and fetch targets (`suppliers:global_ai_model_config`)
7. Make minimal, scoped changes
8. Manually run the user flow, admin flow, and permission wall checks described in Section 12
9. Note any `CORE_TABLES` entries that may be stale relative to the current `contracts` schema

---

## 15. Quick Reference

| Area | Primary files |
|---|---|
| Model | `reports/models.py` |
| All logic | `reports/views.py` |
| SQL safety | `reports/utils.py` |
| Forms | `reports/forms.py` |
| URLs | `reports/urls.py` |
| Admin registration | `reports/admin.py` |
| Admin workspace UI | `reports/templates/reports/admin_dashboard.html` |
| User dashboard | `reports/templates/reports/user_dashboard.html` |
| Global nav coupling | `templates/base_template.html` |

**Main cross-app dependencies:** `users.user_settings.UserSettings`, `suppliers.openrouter_config`, `suppliers:global_ai_model_config` (JS fetch target), `contracts_*` tables (hardcoded in `CORE_TABLES`)

**Security-sensitive areas:** `is_safe_select` / `run_select` in `utils.py`; ownership check in `run_report` / `export_report` / `request_change`; `@user_passes_test(_is_admin)` on all admin views

**Riskiest edits:**
- Renaming `reports:my_requests` or `reports:admin_save_ai_settings` URL names (breaks global nav)
- Changing `SQLUpdateForm` field names (breaks admin JS copy flow)
- Modifying `CORE_TABLES` without verifying current `contracts` table names
- Weakening the `_is_admin` / `is_superuser` check on admin views
- Bypassing `utils.run_select` for any SQL execution path


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
