# AGENTS.md — `reports` app
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

Read `reports/CONTEXT.md` first. This file adds safe-edit guidance for AI coding agents; it does not repeat the context file.

---

## 1. Purpose of This File

Defines how to safely modify the `reports` app. Every rule here is grounded in the actual code. This app is a **feature app** (reporting help-desk + admin SQL workspace with optional Anthropic-powered SQL generation), not a core domain app.

---

## 2. App Scope

**Owns:**
- `ReportRequest` lifecycle: user submits → admin writes SQL → user runs/exports
- SQL safety enforcement (`utils.py`)
- Synchronous **Anthropic Claude** SQL generation for superusers (`admin_ai_generate` → `ANTHROPIC_API_KEY`, model `claude-haiku-4-5-20251001`)
- Table-filtered schema context in `contracts.utils.contracts_schema.generate_db_schema_snapshot()` (replaces the old `CORE_TABLES` + streaming flow)

**Does not own:**
- The `contracts_*` tables it queries — those belong to the `contracts` app (and related models)
- OpenRouter / global shared model UI — that remains in the `suppliers` app for other features; the `reports` admin no longer calls `suppliers:global_ai_model_config` or `openrouter_config` from this app
- The global “Reports AI” settings form in `base_template.html` (removed; `users:settings-*` and other context processor keys may still exist for unrelated UI)

---

## 3. Read This Before Editing

### Before changing models
- `reports/models.py` — single model, UUID PK, status/category choices as string constants
- `reports/migrations/0001_initial.py` — only migration; no subsequent schema changes
- `reports/admin.py` — uses `status`, `category`, `created_at`, `last_run_at` directly
- `reports/forms.py` — `SQLUpdateForm` exposes `sql_query` and `context_notes` to admins (no AI fields)

### Before changing views
- `reports/views.py` — user + admin + `admin_ai_generate` (no OpenRouter imports)
- `reports/utils.py` — `is_safe_select`, `apply_limit`, `run_select` are called by multiple views
- `contracts/utils/contracts_schema.py` — `generate_db_schema_snapshot()` for AI table selection + introspected text

### Before changing templates
- `reports/templates/reports/admin_dashboard.html` — inline `fetch` to `reports:admin_ai_generate`, `#id_sql_query`, preview/save wiring; no `EventSource`
- `templates/base_template.html` — `reports:my_requests` only for this app’s global nav (no `reports:admin_save_ai_settings`)

### Before changing URL names
- Search `templates/base_template.html`, `reports/templates/reports/*.html`, and `reports/views.py` for any `reverse(...)` or `{% url '...' %}` referencing `reports:` names

### Before changing SQL safety logic
- `reports/utils.py` — `is_safe_select`, `apply_limit`, `run_select` are the only guard between user-visible SQL and the database; used by `run_report`, `export_report`, and `admin_preview_sql`

---

## 4. Local Architecture / Change Patterns

- All business logic for this app lives in `reports/views.py`. The `reports/services/` directory is empty; there are no service modules, selectors, or tasks.
- `reports/utils.py` handles SQL validation and CSV serialization only — it is stateless and has no side effects (except the shared `generate_db_schema_snapshot` used by the contracts schema helper).
- The admin template contains JavaScript for `admin_ai_generate`, preview `context_notes` copy, and save SQL hidden field; no SSE.
- No signals, no Celery tasks, no management commands in this app.
- The `_is_admin` guard function in `views.py` (checks `user.is_superuser`) is the only permission helper; it is not shared with other apps.

---

## 5. Files That Commonly Need to Change Together

| Change | Files that must move together |
|---|---|
| Add a field to `ReportRequest` | `models.py` + new migration + `admin.py` (readonly_fields) + `forms.py` if admin-editable + relevant templates |
| Change status values (`pending`/`completed`/`change`) | `models.py` constants + all `views.py` references + templates that branch on status + `admin.py` list_filter |
| Change a URL name | `urls.py` + every `{% url 'reports:...' %}` in templates + any `reverse('reports:...')` in `views.py` |
| Add a new admin view | `views.py` + `urls.py` + `admin_dashboard.html` (or new template) |
| Change AI schema or Anthropic behavior | `views.py` (`admin_ai_generate`) + `contracts.utils.contracts_schema` + `admin_dashboard.html` fetch body / IDs |

---

## 6. Cross-App Dependency Warnings

### This app depends on:

- **`users` app** — `ReportRequest.user` FK to `AUTH_USER_MODEL` (no `UserSettings` keys in `reports` views for AI)
- **`contracts` app** — `contracts.utils.contracts_schema.generate_db_schema_snapshot` composes the introspected schema; introspection is implemented in `reports.utils.generate_db_schema_snapshot`
- **`requests` + Anthropic** — `admin_ai_generate` POSTs to `https://api.anthropic.com/v1/messages`

### Other apps that depend on this app:

- **`templates/base_template.html`** — `reports:my_requests` in the user menu
- No other app imports from `reports` in Python in typical setups (search before assuming)

---

## 7. Security / Permissions Rules

- **All views** are decorated with `@login_required`. Do not remove this.
- **Admin views** (`admin_dashboard`, `admin_save_sql`, `admin_delete_request`, `admin_preview_sql`, `admin_ai_generate`) add `@user_passes_test(_is_admin)` which checks `user.is_superuser`. Do not weaken this to group-based checks without a security review.
- **Object-level ownership**: `run_report`, `export_report`, and `request_change` manually verify `rr.user_id == request.user.id or request.user.is_superuser`. If you add new views that access `ReportRequest` by PK, replicate this check.
- **SQL safety**: `is_safe_select` in `utils.py` is the only barrier between stored SQL and the database. Do not bypass it with direct `connection.cursor().execute()` calls in new views.
- **CSV export**: `export_report` streams up to 50,000 rows without pagination. Treat it as a sensitive download path; preserve the ownership check and the `run_select` call.
- **`admin_ai_generate`**: Superuser-only, POST-only, returns generated text only; still validate prompts are non-empty. Do not auto-run returned SQL.

---

## 8. Model and Schema Change Rules

- `ReportRequest` is the only model. It has a UUID PK — do not change to integer without a data migration.
- Status values are string constants defined on the model class and referenced by string in `views.py` filter calls. If you add or rename a status, update: `models.py` choices, all `views.py` filter/branch logic, and any template `{% if rr.status == "..." %}` checks.
- `ai_prompt` and `ai_result` fields exist on the model but are never populated by any current view. Do not remove them without checking for future use or data already stored.
- Only one migration exists (`0001_initial.py`). New field additions require a new migration. Coordinate with `startup.sh` if `RESET_REPORTS=1` is used in staging — that fake-resets migrations.
- `last_run_at` and `last_run_rowcount` are updated via `update_fields` in `run_report`. If you add audit fields, follow the same targeted-save pattern.

---

## 9. View / URL / Template Change Rules

- URL name `reports:my_requests` is used in `base_template.html`. Renaming it breaks the global menu — search globally before touching.
- `admin_preview_sql` re-renders `reports/admin_dashboard.html` with `preview_columns` / `preview_rows`. If you refactor the admin template, preserve these keys.
- `admin_dashboard` passes `pending` as a queryset of `ReportRequest` objects filtered to `status__in=[STATUS_PENDING, STATUS_CHANGE]`. Templates iterate this directly.
- The JS in `admin_dashboard.html` must keep DOM IDs: `id_sql_query`, `id_context_notes` (Django form defaults), and `btn-generate-sql` / `ai-prompt` / `ai-error` for the new AI flow.

---

## 10. Forms / Serializers / Input Validation Rules

- `ReportRequestForm` intentionally exposes only `title`, `description`, `category` — never `sql_query`, `status`, or `user`. Do not add fields that let users set their own status or inject SQL.
- `SQLUpdateForm` exposes `sql_query` and `context_notes` for admins only. If you add fields here, confirm the view passes the right `instance` and that `admin_save_sql` saves them correctly.
- All SQL execution goes through `utils.run_select` → `utils.is_safe_select` → `utils.apply_limit`. Do not accept raw SQL from user-facing forms or views.
- `request_change` appends a timestamped string to `context_notes` using string concatenation. If you change this format, existing notes remain in the old format — handle gracefully.

---

## 11. Background Tasks / Signals / Automation Rules

**None.** There are no signals, no Celery tasks, no cron jobs, and no management commands in this app. `admin_ai_generate` is a synchronous HTTP round-trip to Anthropic (no WebSockets, no Channels).

---

## 12. Testing and Verification Expectations

**There are no real tests.** `reports/tests.py` contains only the autogenerated `TestCase` stub.

After making changes, manually verify:

1. **User flow**: log in as a non-superuser → visit `/reports/` → submit a new request → confirm it appears as pending
2. **Admin flow**: log in as superuser → `/reports/admin/` → select a pending request → paste SQL → Preview → Save → confirm status becomes Completed
3. **Run/Export**: as the owning user → click Run on a completed report → confirm results render → click Export CSV → confirm file downloads
4. **Change request**: as owner → click Request Changes on a completed report → confirm status flips to `change`
5. **AI generate**: in admin, enter a prompt (with `ANTHROPIC_API_KEY` set) → Generate SQL → confirm the SQL text appears in the editor; confirm errors show in `#ai-error`
6. **Permission wall**: log in as non-superuser → attempt `/reports/admin/` and POST to `/reports/admin/ai/generate/` → not allowed
7. **Base template**: confirm `{% url 'reports:my_requests' %}` still resolves

---

## 13. Known Footguns

- **Schema table filter** lives in `contracts.utils.contracts_schema`—if the DB gains new `contracts_*` / `auth_user` / content-type needs, update `_is_report_ai_schema_table` / `generate_db_schema_snapshot` rather than duplicating lists in `views.py`.
- **JS form ID coupling**: `admin_dashboard.html` uses `document.getElementById('id_sql_query')`. If `SQLUpdateForm` field names change, the AI fill flow breaks silently.
- **Status string constants**: Views filter by `status__in=[ReportRequest.STATUS_PENDING, ReportRequest.STATUS_CHANGE]`. Adding a new status without updating every queryset filter will cause requests to disappear from the admin list.
- **`ai_prompt` / `ai_result` fields are never written**: they exist in the model/DB but no view populates them.
- **`export_report` does not stream**: it calls `run_select(limit=50000)` and holds the full result in memory before writing CSV. Very large result sets will cause memory pressure.
- **No test coverage**: any refactor of `utils.py` SQL safety logic carries silent regression risk.

---

## 14. Safe Change Workflow

1. Read `reports/CONTEXT.md` for the big picture
2. Read the specific files involved (model, view, template, form as appropriate)
3. Search `templates/base_template.html` and all `reports/templates/` for URL name and context key references
4. If touching AI schema or the Anthropic call, read `contracts.utils.contracts_schema` and `reports/views.py` `admin_ai_generate` together
5. If touching the admin template JS, trace the DOM IDs and the `admin_ai_generate` endpoint
6. Make minimal, scoped changes
7. Manually run the user flow, admin flow, and permission wall checks described in Section 12

---

## 15. Quick Reference

| Area | Primary files |
|---|---|
| Model | `reports/models.py` |
| All logic | `reports/views.py` |
| SQL safety | `reports/utils.py` |
| AI schema helper | `contracts/utils/contracts_schema.py` |
| Forms | `reports/forms.py` |
| URLs | `reports/urls.py` |
| Admin registration | `reports/admin.py` |
| Admin workspace UI | `reports/templates/reports/admin_dashboard.html` |
| User dashboard | `reports/templates/reports/user_dashboard.html` |
| Global nav coupling | `templates/base_template.html` (`reports:my_requests` only) |

**Main cross-app dependencies:** `contracts.utils.contracts_schema` (table filter + snapshot), `ANTHROPIC_API_KEY` env, `users` (auth / FK)

**Security-sensitive areas:** `is_safe_select` / `run_select` in `utils.py`; ownership check in `run_report` / `export_report` / `request_change`; `@user_passes_test(_is_admin)` on all admin views

**Riskiest edits:**
- Renaming `reports:my_requests` (breaks global menu)
- Changing `SQLUpdateForm` field names (breaks admin JS)
- Weakening the `_is_admin` / `is_superuser` check on admin views
- Bypassing `utils.run_select` for any SQL execution path

## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**When editing templates:** if you encounter Tailwind utility classes, replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
