# Reports Context

## 1. Purpose
`reports` is the project’s ad-hoc reporting workspace. End users submit report requests describing the data they need, and site staff (superusers) author SQL, run the queries against the core schema, and deliver CSV exports. The app also hosts an AI-assisted admin panel that injects schema context and calls the **Anthropic Claude API** to return a single T-SQL `SELECT` for the admin to review and run (no OpenRouter, no streaming, no per-user model preferences in this app).

## 2. App Identity
- Django app name: `reports`
- AppConfig: `ReportsConfig` (`reports/apps.py`)
- Filesystem path: `reports/`
- Classification: feature app (reporting/help desk) that bridges the public web UI, the Django admin, and cross-app integrations for schema introspection and AI helpers.

## 3. High-Level Responsibilities
- Persist user requests for new reports, including status (`pending`/`completed`/`change`), SQL drafts, and contextual notes (`reports/models.py`).
- Render the late user dashboard, request form, run results page, and change-request workflow under `/reports/` (`reports/views.py`, `reports/templates/reports`).
- Supply an admin workspace that loads pending requests, lets admins preview/run raw SQL, mark requests complete, and delete bad requests (`reports/views.py`, `reports/templates/reports/admin_dashboard.html`).
- Execute only safe, read-only SELECT statements with limits and dialect adjustments before displaying runs or exporting CSV (`reports/utils.py`).
- For superusers, call Anthropic **Claude Haiku** (`claude-haiku-4-5-20251001`) with a system prompt and DB schema built from `contracts.utils.contracts_schema.generate_db_schema_snapshot()`; require `ANTHROPIC_API_KEY` in the environment.

## 4. Key Files and What They Do
- `models.py`: defines the single `ReportRequest` entity (UUID PK, user FK, status/category choices, SQL/context metadata, `last_run` timestamps) that tracks the lifecycle of every request.
- `views.py`: hosts user views (`user_dashboard`, `request_report`, `run_report`, `export_report`, `request_change`) plus the admin suite (`admin_dashboard`, `admin_save_sql`, `admin_preview_sql`, `admin_ai_generate`, `admin_delete_request`) and SQL safety execution via `utils` (no OpenRouter or `UserSettings` AI keys).
- `urls.py`: exposes all routes under `app_name = "reports"`, including `admin_ai_generate` (synchronous JSON POST) for AI SQL.
- `forms.py`: supplies `ReportRequestForm` for user submissions and `SQLUpdateForm` for admins editing SQL/context notes (no AI model fields).
- `admin.py`: registers `ReportRequest` with list filters, search, and read-only metadata fields.
- `utils.py`: implements `is_safe_select`/`apply_limit`, `run_select`, CSV serialization, and a lower-level `generate_db_schema_snapshot` used by the contracts schema helper to introspect tables.
- `contracts/utils/contracts_schema.py`: `generate_db_schema_snapshot()` filters tables to `contracts_*` / `suppliers_*` / `products_*` (when present) plus `auth_user` and `django_content_type`, then delegates to `reports.utils.generate_db_schema_snapshot` for column/FK text.
- `templates/reports/*`: the four templates drive the user dashboard, request form, run results, and the admin workspace with a simple `fetch` POST to `admin_ai_generate` (no EventSource).
- `templates/base_template.html`: global navigation link to `reports:my_requests` (the former OpenRouter “Save Model Defaults” form for this app was removed; other apps may still use `users.context_processors` for unrelated defaults).
- `static/css/base.css` & `static/css/dark-mode.css`: define `.reports-admin`/`.reports-scope` styles so both dashboards render consistently in light and dark modes.
- `docs/design.md` and `docs/tasklist.md`: record the original NLQ/phase plans for `reports` (multi-model, query planner, widgets) even though the current code remains simpler.
- `startup.sh`: honors `RESET_REPORTS=1` to fake-reset this app’s migrations during staging or emergency deploys before re-applying (`startup.sh`).

## 5. Data Model / Domain Objects
- `ReportRequest` (only model in `reports/models.py`):
  - UUID primary key and `user` FK to `AUTH_USER_MODEL` with `related_name="report_requests"`.
  - `title`, `description`, and `category` (`contract`, `supplier`, `nsn`, `other`) describe user intent.
  - `status` (pending/completed/change) tracks state transitions referenced by both user and admin views.
  - `sql_query`, `context_notes`, `ai_prompt`, and `ai_result` store the admin SQL, memo, and future AI text (currently only SQL/context are edited in forms).
  - `last_run_at`/`last_run_rowcount` record the most recent execution details; auto timestamps enforce ordering (newest first).
  - String representation surfaces `title` and `status` for logs/admin.

## 6. Request / User Flow
1. Users visit `/reports/` (and `/reports/my/`) to see their pending/completed/change requests via `user_dashboard`, which renders `reports/templates/reports/user_dashboard.html`, reuses `ReportRequestForm`, and shows run/export buttons (`reports/views.py`).
2. Submitting `POST /reports/request/` saves a new `ReportRequest` in `pending` status (`ReportRequestForm` restricts fields to title, description, category).
3. Completed reports show `Run` and `Export CSV` actions that call `run_report` and `export_report`; these views run the stored SQL through `run_select` (1000 row preview limit) or `rows_to_csv` (50k row limit) and render `run_results.html` or stream a CSV attachment.
4. Users request changes via `/reports/request-change/<uuid>/` which appends a timestamped note to `context_notes`, flips status to `change`, and lets them revert to pending.
5. Superusers open `/reports/admin/` to load pending requests, select one, preview SQL, save the query (marking the request `completed`), or delete it. The right-hand panel posts a natural-language prompt to `admin_ai_generate` and fills the SQL editor (`#id_sql_query`) with the returned `sql` JSON field.

## 7. Templates and UI Surface Area
- `reports/templates/reports/user_dashboard.html`: server-rendered dashboard, grouped panels for new requests, pending/completed/change lists, `Request Changes` toggles, run/export CTA buttons, and a `Reports` nav link if the user is superuser.
- `reports/templates/reports/request_form.html`: minimal page for standalone report creation using the same `ReportRequestForm`.
- `reports/templates/reports/run_results.html`: tabular display of the latest query results plus export/back buttons.
- `reports/templates/reports/admin_dashboard.html`: split grid with pending request list, SQL editor/preview, and an AI column using Bootstrap 5 (prompt textarea, “Generate SQL” button, error alert, no SSE).
- Global navigation: `templates/base_template.html` exposes a `Reports` link via `{% url 'reports:my_requests' %}`; there is no `reports` AI settings form in the base template anymore.
- Styling: `static/css/base.css` and `static/css/dark-mode.css` scope `.reports-admin`/`.reports-scope` panels, buttons, preview tables, and dark-mode overrides so the dashboards look consistent with the rest of the theme. Prefer Bootstrap 5 + `app-core.css` for new markup in this app.

## 8. Admin / Staff Functionality
- `admin.py` registers `ReportRequest` with filters on `status`, `category`, and timestamps; `created_at`, `updated_at`, `last_run` fields are read-only.
- The admin workspace lists pending/change requests, loads SQL via `SQLUpdateForm`, allows saving SQL (marking the request `completed`), deleting requests, and previewing SQL. The AI path is synchronous JSON only (`admin_ai_generate`).

## 9. Forms, Validation, and Input Handling
- `ReportRequestForm` (in `forms.py`) is the only form users see; it only accepts `title`, `description`, and `category`, and renders the description as a textarea.
- `SQLUpdateForm` manages the `sql_query` and `context_notes` fields for admins; `sql_query` uses a larger textarea with spellcheck disabled.
- `utils.is_safe_select`/`apply_limit`/`run_select` enforce read-only SQL, single statement, forbid dangerous keywords, and inject limits/TOP depending on the vendor.
- `request_change` sanitizes status updates and prefixes user messages with a timestamp when appending to `context_notes`.
- `admin_save_sql` rejects empty SQL, sets status to `completed`, and saves context notes while using `messages` for feedback.
- `admin_ai_generate` accepts `POST` with `prompt` (and CSRF); returns JSON `{ "sql": "..." }` or `{ "error": "..." }`.

## 10. Business Logic and Services
- User flows, SQL validation, and CSV export are orchestrated in `reports/views.py`. `admin_ai_generate` builds `schema_text` from `contracts.utils.contracts_schema.generate_db_schema_snapshot()` (replaces the removed `CORE_TABLES` allowlist in `views.py`), then POSTs to `https://api.anthropic.com/v1/messages` with the standard `anthropic-version: 2023-06-01` header and `x-api-key` from `ANTHROPIC_API_KEY`.
- The older `utils.generate_db_schema_snapshot` remains the low-level introspection primitive; the `contracts` wrapper owns which tables are included for the AI.

## 11. Integrations and Cross-App Dependencies
- `users` app: `ReportRequest.user` FK only (this app no longer uses `UserSettings` for `reports_ai_model` / `reports_ai_fallbacks`).
- `contracts` app: `contracts.utils.contracts_schema.generate_db_schema_snapshot` defines table filtering and calls `reports.utils.generate_db_schema_snapshot` for the actual introspection string.
- `STATZWeb/urls.py`: mounts `reports.urls` under `/reports/` so the UI routes become reachable from the main project.
- `templates/base_template.html`: adds a `Reports` nav link only (`reports:my_requests`).
- `STATZWeb/settings.py`: exposes the app via `reports.apps.ReportsConfig` and `REPORT_CREATOR_EMAIL` as before; `reports` does not read `OPENROUTER_*` in views.
- `startup.sh`: respects `RESET_REPORTS=1` by faking down/up the `reports` migrations.
- External service: `reports/views.py` uses the `requests` library for a single Anthropic `POST` (no streaming).

## 12. URL Surface / API Surface
| Path | Purpose |
| --- | --- |
| `/reports/` & `/reports/my/` | `user_dashboard` shows the current user’s pending, completed, and change requests plus the inline `ReportRequestForm`. |
| `/reports/request/` | `request_report` saves a new request from the form. |
| `/reports/run/<uuid:pk>/` | `run_report` executes the stored SQL (limit 1k rows) and renders `run_results.html`. |
| `/reports/export/<uuid:pk>/` | `export_report` streams `rows_to_csv` output with a `Content-Disposition` CSV attachment (limit 50k rows). |
| `/reports/request-change/<uuid:pk>/` | `request_change` lets the owner mark a request as `change` or send it back to `pending` while appending notes. |
| `/reports/admin/` | `admin_dashboard` lists pending requests, facades SQL editing/preview, and surfaces the AI panel. |
| `/reports/admin/save/<uuid:pk>/` | `admin_save_sql` stores the SQL/context and marks the request completed. |
| `/reports/admin/delete/<uuid:pk>/` | `admin_delete_request` removes the request (superuser only). |
| `/reports/admin/preview/<uuid:pk>/` | `admin_preview_sql` runs the tentative SQL and re-renders the admin page with `preview_columns`/`preview_rows`. |
| `/reports/admin/ai/generate/` | `admin_ai_generate` (POST, superuser) returns JSON `{ "sql": "..." }` from Anthropic. |

## 13. Permissions / Security Considerations
- All views are decorated with `@login_required`; admin views add `@user_passes_test(_is_admin)` to ensure only superusers access the workspace.
- `run_report`, `export_report`, and `request_change` manually check that `request.user` is either the owner (`rr.user_id == request.user.id`) or a superuser, returning `HttpResponseBadRequest` otherwise.
- `admin_save_sql` refuses to mark a request completed without SQL (`messages.error` if `sql_query` blank).
- `admin_ai_generate` is `@require_POST` and superuser-only; it rejects empty prompts and does not execute generated SQL (only the SQL editor and preview/save paths run queries).
- `utils.is_safe_select` blocks DML/DDL keywords, forbids multiple statements, and enforces SELECT/CTE beginnings before executing any query.

## 14. Background Processing / Scheduled Work
No Celery tasks, cron jobs, or management commands exist inside `reports`. The Anthropic call in `admin_ai_generate` is a normal synchronous request/response.

## 15. Testing Coverage
`tests.py` contains only the autogenerated `TestCase` stub; no unit or integration tests cover the dashboard, admin workspace, or SQL validation logic. This means behavior is primarily exercised through manual QA.

## 16. Migrations / Schema Notes
Only one migration exists (`reports/migrations/0001_initial.py`), which mirrors `ReportRequest`’s fields and FK to `AUTH_USER_MODEL`. There are no subsequent schema changes, so the table structure is stable and governed by this single migration.

## 17. Known Gaps / Ambiguities
- `docs/design.md` and `docs/tasklist.md` describe a richer NLQ pipeline with `Report`, `ReportChange`, report templates, caching, and conversational builders, but none of those models/services/controllers exist in the current code; the app only persists `ReportRequest` and uses raw SQL.
- `ReportRequest` exposes `ai_prompt` and `ai_result` fields that are never populated anywhere in the codebase, suggesting either leftover schema or future work.
- The `reports/services/` directory is empty; business logic currently lives in `reports/views.py` rather than dedicated service modules described in the docs.
- There are no automated tests, so regressions in SQL validation or the Anthropic call depend on manual verification.

## 18. Safe Modification Guidance for Future Developers / AI Agents
1. When changing SQL execution paths, revisit `reports/utils.py`—`is_safe_select`, `apply_limit`, and `run_select` enforce single-statement read-only semantics, vendor-specific limits, and row caps used by `run_report`, `export_report`, and `admin_preview_sql`.
2. When changing which tables appear in the AI schema prompt, edit `contracts.utils.contracts_schema` (`_is_report_ai_schema_table` / `generate_db_schema_snapshot`) instead of reintroducing a `CORE_TABLES` list in `views.py`.
3. The admin `fetch` in `admin_dashboard.html` posts to `reports:admin_ai_generate` and uses `#id_sql_query`—keep those stable or update both template and any preview/save copy logic.
4. Before renaming the `ReportRequest` model or its fields, search for `reports:` URLs, `templates/reports`, and `STATIC` CSS selectors (`.reports-admin`, `.reports-scope` in `static/css/base.css`) because the UI, navigation, and styling all assume those names.
5. Deploy-time resets (e.g., `startup.sh` with `RESET_REPORTS=1`) fake down/up this app’s migrations; coordinate with ops if you add real schema migrations so that the reset sequence remains safe.

## 19. Quick Reference
- **Primary model:** `ReportRequest` (`reports/models.py`) – statuses, categories, SQL/context metadata, last-run audit, user FK.
- **Main URLs:** `/reports/` (user dashboard), `/reports/request/`, `/reports/run/<uuid>/`, `/reports/export/<uuid>/`, `/reports/admin/` + `/reports/admin/*` (SQL save, delete, preview, `admin_ai_generate`).
- **Key templates:** `user_dashboard.html`, `request_form.html`, `run_results.html`, and `admin_dashboard.html` (AI `fetch` + error alert).
- **Key dependencies:** `contracts.utils.contracts_schema` (AI schema), `ANTHROPIC_API_KEY` env, `users` (auth/`ReportRequest` FK), `STATZWeb` (URL include).
- **Risky files:** `reports/views.py` (SQL and Anthropic call), `reports/utils.py` (SQL safety), `contracts/utils/contracts_schema.py` (table filter for AI), `reports/templates/reports/admin_dashboard.html` (JS and `#id_sql_query`).

## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode overrides via `body.dark`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
