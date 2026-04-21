# Reports Context

## 1. Purpose
`reports` is the project’s ad-hoc reporting workspace. End users submit report requests describing the data they need, and site staff (superusers) author SQL, run the queries against the core schema, and deliver CSV exports. The app also hosts an AI-assisted admin panel that injects schema context, hits OpenRouter for SQL suggestions, and keeps per-user model preferences in sync.

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
- Wire up OpenRouter/Azure settings so the admin panel can stream AI tokens, copy generated SQL into the editor, and persist per-user AI preferences via `UserSettings` (`reports/views.py`, `templates/base_template.html`).

## 4. Key Files and What They Do
- `models.py`: defines the single `ReportRequest` entity (UUID PK, user FK, status/category choices, SQL/context metadata, `last_run` timestamps) that tracks the lifecycle of every request.
- `views.py`: hosts user views (`user_dashboard`, `request_report`, `run_report`, `export_report`, `request_change`) plus the admin suite (`admin_dashboard`, `admin_save_sql`, `admin_preview_sql`, `admin_ai_stream`, `admin_save_ai_settings`, `admin_delete_request`), the SQL safety helpers, and the OpenRouter streaming logic.
- `urls.py`: exposes all routes under `app_name = "reports"`, including user actions, admin workspace entry points, and SSE endpoints such as `admin_ai_stream`.
- `forms.py`: supplies `ReportRequestForm` for user submissions and `SQLUpdateForm` for admins editing SQL/context notes.
- `admin.py`: registers `ReportRequest` with list filters, search, and read-only metadata fields.
- `utils.py`: implements `is_safe_select`/`apply_limit`, `run_select`, CSV serialization, and `generate_db_schema_snapshot` so the AI prompt mingles introspected schema and obeys read-only guards.
- `templates/reports/*`: the four templates drive the user dashboard (`user_dashboard.html`), request form, run results, and the JavaScript-heavy admin workspace with AI stream controls.
- `templates/base_template.html`: global navigation links to `reports:my_requests` and the AI settings form that posts to `reports:admin_save_ai_settings`, keeping the workspace discoverable and user preferences surfaced.
- `static/css/base.css` & `static/css/dark-mode.css`: define `.reports-admin`/`.reports-scope` styles so both dashboards render consistently in light and dark modes.
- `docs/design.md` and `docs/tasklist.md`: record the original NLQ/phase plans for `reports` (multi-model, query planner, widgets) even though the current code remains simpler.
- `startup.sh`: honors `RESET_REPORTS=1` to fake-reset this app’s migrations during staging or emergency deploys before re-applying (`startup.sh`).

## 5. Data Model / Domain Objects
- `ReportRequest` (only model in `reports/models.py`):
  - UUID primary key and `user` FK to `AUTH_USER_MODEL` with `related_name="report_requests"`.
  - `title`, `description`, and `category` (`contract`, `supplier`, `nsn`, `other`) describe user intent.
  - `status` (pending/completed/change) tracks state transitions referenced by both user and admin views.
  - `sql_query`, `context_notes`, `ai_prompt`, and `ai_result` store the admin SQL, memo, and future AI text (currently only SQL/context are edited).
  - `last_run_at`/`last_run_rowcount` record the most recent execution details; auto timestamps enforce ordering (newest first).
  - String representation surfaces `title` and `status` for logs/admin.

## 6. Request / User Flow
1. Users visit `/reports/` (and `/reports/my/`) to see their pending/completed/change requests via `user_dashboard`, which renders `reports/templates/reports/user_dashboard.html`, reuses `ReportRequestForm`, and shows run/export buttons (`reports/views.py`).
2. Submitting `POST /reports/request/` saves a new `ReportRequest` in `pending` status (`ReportRequestForm` restricts fields to title, description, category).
3. Completed reports show `Run` and `Export CSV` actions that call `run_report` and `export_report`; these views run the stored SQL through `run_select` (1000 row preview limit) or `rows_to_csv` (50k row limit) and render `run_results.html` or stream a CSV attachment.
4. Users request changes via `/reports/request-change/<uuid>/` which appends a timestamped note to `context_notes`, flips status to `change`, and lets them revert to pending.
5. Superusers open `/reports/admin/` to load pending requests, select one, preview SQL, save the query (marking the request `completed`), or delete it. The admin template also hosts the AI streamer (SSE to `admin_ai_stream`) so generated SQL can be copied into the editor.
6. AI preferences persist per user (model, fallbacks) via `/reports/admin/ai/settings/` and tie into the global settings widget in `templates/base_template.html` so the same defaults show up across the site.

## 7. Templates and UI Surface Area
- `reports/templates/reports/user_dashboard.html`: server-rendered dashboard, grouped panels for new requests, pending/completed/change lists, `Request Changes` toggles, run/export CTA buttons, and a `Reports` nav link if the user is superuser.
- `reports/templates/reports/request_form.html`: minimal page for standalone report creation using the same `ReportRequestForm`.
- `reports/templates/reports/run_results.html`: tabular display of the latest query results plus export/back buttons.
- `reports/templates/reports/admin_dashboard.html`: split grid (as styled in `static/css/base.css`) with pending request list, SQL editor/preview column pane, and AI control panel (radios, schema toggles, SSE textarea, copy buttons). The embedded `<script>` wires `EventSource` to `admin_ai_stream`, copies AI output into the SQL editor, and posts to `suppliers:global_ai_model_config` to save shared models.
- Global navigation: `templates/base_template.html` exposes a `Reports` link and the AI settings form (`settings-ai-model`, `settings-ai-fallbacks`, hidden form posting to `reports:admin_save_ai_settings`).
- Styling: `static/css/base.css` and `static/css/dark-mode.css` scope `.reports-admin`/`.reports-scope` panels, buttons, preview tables, and dark-mode overrides so the dashboards look consistent with the rest of the theme.

## 8. Admin / Staff Functionality
- `admin.py` registers `ReportRequest` with filters on `status`, `category`, and timestamps; `created_at`, `updated_at`, `last_run` fields are read-only.
- The admin workspace (`admin_dashboard` + template) lists pending/change requests, loads SQL via `SQLUpdateForm`, allows saving SQL (marking the request `completed`), deleting requests, previewing SQL results (calls `run_select` with more restrictive limit), and streaming AI drafts.
- AI panel can mark a shared OpenRouter model for replacement via POST to `suppliers:global_ai_model_config` (superuser only) and displays the stored/fallback model info returned by `suppliers.openrouter_config.get_openrouter_model_info()`.

## 9. Forms, Validation, and Input Handling
- `ReportRequestForm` (in `forms.py`) is the only form users see; it only accepts `title`, `description`, and `category`, and renders the description as a textarea.
- `SQLUpdateForm` manages the `sql_query` and `context_notes` fields for admins; `sql_query` uses a larger textarea with spellcheck disabled.
- `utils.is_safe_select`/`apply_limit`/`run_select` enforce read-only SQL, single statement, forbid dangerous keywords, and inject limits/TOP depending on the vendor.
- `request_change` sanitizes status updates and prefixes user messages with a timestamp when appending to `context_notes`.
- `admin_save_sql` rejects empty SQL, sets status to `completed`, and saves context notes while using `messages` for feedback.
- `admin_save_ai_settings` accepts JSON or form POSTs, persists `reports_ai_model`/`reports_ai_fallbacks` using `UserSettings.save_setting`, and returns JSON when called via AJAX or redirects with `messages` otherwise.

## 10. Business Logic and Services
- User flows, SQL validation, CSV export, and AI streaming are all orchestrated in `reports/views.py`. Key logic includes `run_report`/`export_report` invoking `run_select`, `admin_preview_sql` rerunning queries for preview, `admin_save_sql` toggling status, and `admin_ai_stream` assembling schema text and hitting OpenRouter via `requests.post` with SSE handling.
- `CORE_TABLES` hardcodes `contracts_*` tables so AI prompts default to the contracts domain; admins can request `full=1` or pass `extra=a,b` to expand the schema sent to `generate_db_schema_snapshot`.
- `utils.generate_db_schema_snapshot` introspects the DB schema (columns, nullability, PK/FK) so prompts contain table/column hints.
- AI streaming view determines SQL dialect from `connection.vendor`, builds system/user prompts, streams SSE tokens (`type: token`/`done`/`error`), and falls back to a mock SQL if `OPENROUTER_API_KEY` is missing.
- The inline admin JavaScript handles the SSE stream, copies parsed SQL into the editor (`copy` button), and posts to `suppliers:global_ai_model_config` to update shared models.

## 11. Integrations and Cross-App Dependencies
- `users` app: `ReportRequest.user` FK and `UserSettings` (the `reports` views read/save `reports_ai_model`/`reports_ai_fallbacks` through `users/user_settings.py`, and the base template reads those settings for the AI drawer).
- `suppliers` app: `reports.views` calls `suppliers.openrouter_config.get_openrouter_model_info`/`get_model_for_request` to show the shared model and pick the effective model; the admin template posts to `suppliers:global_ai_model_config` to update the shared config, which is a superuser-only view in `suppliers/views.py`.
- `contracts` app: the `CORE_TABLES` list references `contracts_*` tables (contracts, CLINs, suppliers, NSNs, payments) to limit the schema snippet sent to OpenRouter, so renaming those tables requires updating `CORE_TABLES`.
- `STATZWeb/urls.py`: mounts `reports.urls` under `/reports/` so the UI routes become reachable from the main project.
- `templates/base_template.html`: adds a `Reports` nav link and the AI settings form that posts to `reports:admin_save_ai_settings`, meaning the app is part of the global settings drawer.
- `STATZWeb/settings.py`: exposes the app via `reports.apps.ReportsConfig` and defines `REPORT_CREATOR_EMAIL` plus a suite of `OPENROUTER_*` env-driven settings that `reports/views.py` consumes (`OPENROUTER_API_KEY`, `_BASE_URL`, `_MODEL`, `_FALLBACKS`, `_HTTP_REFERER`, `_X_TITLE`).
- `startup.sh`: respects `RESET_REPORTS=1` by faking down/up the `reports` migrations, a useful safety valve when the schema drifts.
- External service: `reports/views.py` depends on the `requests` library to connect to OpenRouter‘s streaming chat endpoint.

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
| `/reports/admin/ai/stream/` | `admin_ai_stream` streams OpenRouter chat tokens as SSE for the AI panel. |
| `/reports/admin/ai/settings/` | `admin_save_ai_settings` persists user preferences for the AI model/fallbacks (JSON or form). |

## 13. Permissions / Security Considerations
- All views are decorated with `@login_required`; admin views add `@user_passes_test(_is_admin)` to ensure only superusers access the workspace.
- `run_report`, `export_report`, and `request_change` manually check that `request.user` is either the owner (`rr.user_id == request.user.id`) or a superuser, returning `HttpResponseBadRequest` otherwise.
- `admin_save_sql` refuses to mark a request completed without SQL (`messages.error` if `sql_query` blank).
- `admin_ai_stream` builds prompts only after verifying a prompt string is present, filters tables via `CORE_TABLES` or user-supplied extras, and uses `utils.is_safe_select`/`generate_db_schema_snapshot` for context; it also falls back to a mock stream if `OPENROUTER_API_KEY` is missing so admins still see a UX even without credentials.
- `utils.is_safe_select` blocks DML/DDL keywords, forbids multiple statements, and enforces SELECT/CTE beginnings before executing any query.
- `requests` to OpenRouter stream via `StreamingHttpResponse` with SSE, so the UI must parse `data:` lines; errors bubble back to the admin page and stop the EventSource.

## 14. Background Processing / Scheduled Work
No Celery tasks, cron jobs, or management commands exist inside `reports`. The only “background” work is the SSE cooking in `admin_ai_stream`, which synchronously posts to OpenRouter, streams tokens, and ends once the stream closes. No scheduled reports or offline exporters are defined inside this app.

## 15. Testing Coverage
`tests.py` contains only the autogenerated `TestCase` stub; no unit or integration tests cover the dashboard, admin workspace, or SQL validation logic. This means behavior is primarily exercised through manual QA.

## 16. Migrations / Schema Notes
Only one migration exists (`reports/migrations/0001_initial.py`), which mirrors `ReportRequest`’s fields and FK to `AUTH_USER_MODEL`. There are no subsequent schema changes, so the table structure is stable and governed by this single migration.

## 17. Known Gaps / Ambiguities
- `docs/design.md` and `docs/tasklist.md` describe a richer NLQ pipeline with `Report`, `ReportChange`, report templates, caching, and conversational builders, but none of those models/services/controllers exist in the current code; the app only persists `ReportRequest` and uses raw SQL.
- `ReportRequest` exposes `ai_prompt` and `ai_result` fields that are never populated anywhere in the codebase, suggesting either leftover schema or future work.
- The `reports/services/` directory is empty; business logic currently lives in `reports/views.py` rather than dedicated service modules described in the docs.
- There are no automated tests, so regressions in SQL validation or AI streaming depend on manual verification.

## 18. Safe Modification Guidance for Future Developers / AI Agents
1. The `CORE_TABLES` list in `reports/views.py` hardcodes `contracts_*` tables; renaming or dropping any of those tables requires updating the list so the AI schema prompt stays relevant.
2. When changing SQL execution paths, revisit `reports/utils.py`—`is_safe_select`, `apply_limit`, and `run_select` enforce single-statement read-only semantics, vendor-specific limits, and row caps used by `run_report`, `export_report`, and `admin_preview_sql`.
3. Updates to AI behavior must consider `suppliers.openrouter_config`/`suppliers:global_ai_model_config`, `UserSettings` (`reports_ai_model`, `reports_ai_fallbacks`), and the settings drawer in `templates/base_template.html`, since multiple entry points share the same preferences.
4. The admin JS copies SSE output into the hidden editor fields and calls `suppliers:global_ai_model_config`; changing those form IDs or endpoints requires updating `reports/templates/reports/admin_dashboard.html` script and the related supplier view.
5. Before renaming the `ReportRequest` model or its fields, search for `reports:` URLs, `templates/reports`, and `STATIC` CSS selectors (`.reports-admin`, `.reports-scope` in `static/css/base.css`) because the UI, navigation, and styling all assume those names.
6. Deploy-time resets (e.g., `startup.sh` with `RESET_REPORTS=1`) fake down/up this app’s migrations; coordinate with ops if you add real schema migrations so that the reset sequence remains safe.

## 19. Quick Reference
- **Primary model:** `ReportRequest` (`reports/models.py`) – statuses, categories, SQL/context metadata, last-run audit, user FK.
- **Main URLs:** `/reports/` (user dashboard), `/reports/request/`, `/reports/run/<uuid>/`, `/reports/export/<uuid>/`, `/reports/admin/` + `/reports/admin/*` (SQL save, delete, preview, AI stream/settings).
- **Key templates:** `user_dashboard.html`, `request_form.html`, `run_results.html`, and `admin_dashboard.html` (AI panel + SSE script).
- **Key dependencies:** `users` (`AUTH_USER_MODEL`, `UserSettings`), `suppliers` (`openrouter_config`, `global_ai_model_config` view), `STATZWeb` (settings/TEMPLATE nav + URL include), OpenRouter env vars (`OPENROUTER_*`).
- **Risky files:** `reports/views.py` (heavy logic and AI streaming), `reports/utils.py` (SQL safety), `reports/templates/reports/admin_dashboard.html` (JS IDs/form wiring), and `static/css/base.css`/`dark-mode.css` (layout/scoping of `.reports-admin`).


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode overrides via `body.dark`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
