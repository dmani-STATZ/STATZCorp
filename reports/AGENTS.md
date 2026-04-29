# AGENTS.md — `reports` app
> Read `reports/CONTEXT.md` first.

## 1. Purpose of This File
Safe-edit guidance for the rebuilt reports backend (ticket flow + report library + versioning + sharing + staff prototype builder).

## 2. App Scope
**Owns:**
- `ReportDraft`, `ReportRequest`, `Report`, `ReportVersion`, `ReportShare`
- SQL safety execution (`reports/utils.py`)
- Superuser AI generation endpoint (`admin_ai_generate`)
- Staff builder flow (`draft_builder`, `draft_iterate`, `draft_promote`, `draft_discard`)

**Does not own:**
- Underlying `contracts_*`, `suppliers_*`, `products_*` schema
- Global project routing mount (`STATZWeb/urls.py`)

## 3. Read This Before Editing
### Before changing models
- `reports/models.py`
- `reports/migrations/0001_initial.py` (historical, keep)
- `reports/migrations/0002_rebuild.py` (active architecture reset)
- `reports/admin.py`
- `reports/forms.py`

### Before changing AI behavior
- `reports/views.py` (`admin_ai_generate` + draft AI calls)
- `contracts/utils/contracts_schema.py`
- `reports/utils.py`

### Before changing URLs
- `reports/urls.py`
- `templates/base_template.html` (`reports:hub` top-level nav link)
- `reports/templates/reports/*.html`

### Before changing templates
All seven templates are production-built Bootstrap 5 UIs. Current template files:
- `reports/templates/reports/hub.html`
- `reports/templates/reports/run_results.html`
- `reports/templates/reports/admin_queue.html`
- `reports/templates/reports/draft_builder.html`
- `reports/templates/reports/draft_iterate.html`
- `reports/templates/reports/share_report.html`

## 4. Local Architecture / Change Patterns
- `Report` is the library item.
- `ReportVersion` is immutable history; `Report.active_version` points to current.
- `ReportRequest` is workflow/ticket metadata and can link to existing or newly spawned reports.
- `ReportDraft` is temporary builder state for `is_staff`.
- `ReportShare` controls user-level sharing and branch permission.

## 5. Files That Commonly Need to Change Together
| Change | Files that must move together |
|---|---|
| Add/edit report request status values (`pending`, `in_progress`, `completed`, `change_requested`) | `models.py` + `views.py` queue filters/forms + `admin.py` |
| Change report lifecycle fields (`active_version`, branching fields) | `models.py` + migration + `views.py` (`admin_save_version`) |
| Change sharing behavior | `models.py` (`ReportShare`) + `forms.py` (`ReportShareForm`) + `views.py` (`share_report`) |
| Change builder behavior | `models.py` (`ReportDraft`) + `forms.py` + `views.py` + draft templates |
| Change request flow modification | `models.py` + migration + `views.py` (`request_change`) + `admin_queue.html` (parent version context card) + `admin_ai_generate` (`existing_sql` parameter) |
| Change URL names | `urls.py` + template `{% url %}` usage + `reverse(...)` call sites |

## 6. Cross-App Dependency Warnings
- Depends on `AUTH_USER_MODEL` for all ownership/share relations.
- Depends on `contracts.utils.contracts_schema.generate_db_schema_snapshot` for AI context.
- `templates/base_template.html` links to `reports:hub`; keep this URL stable or update both sides.

## 7. Security / Permissions Rules
- Keep `@login_required` on all views.
- Keep `_is_admin` (`is_superuser`) on admin queue + AI + admin mutating endpoints.
- Keep `_is_staff_builder` (`is_staff`) on all draft builder endpoints.
- `draft_promote` and `draft_discard` must enforce `draft.owner == request.user`.
- Do not bypass `run_select` SQL safety for run/preview/export.
- Preserve object-level access checks for owner/company/shared report visibility.

## 8. Model and Schema Change Rules
- All report models use UUID PKs; keep UUID unless explicit migration strategy says otherwise.
- `ReportVersion` is immutable: never edit existing rows in-place to represent new SQL.
- New SQL must create a new `ReportVersion`, then repoint `Report.active_version`.
- Keep `ReportVersion` unique per (`report`, `version_number`).
- Keep branch metadata semantics (`branched_from`, `branch_count`, `keep_original`, `is_branch_request`) coherent across request and save-version flows.
- **`ReportRequest.parent_version`** is intentionally a snapshot FK, not a live reference. It should never be updated after the request is created. If the linked report's `active_version` changes, `parent_version` stays pointing at the original.

## 9. View / URL / Template Rules
- Primary user landing URL is `reports:hub` (not `reports:my_requests`).
- Keep admin queue URL names stable:
  - `reports:admin_queue`
  - `reports:admin_save_version`
  - `reports:admin_preview_sql`
  - `reports:admin_update_request`
  - `reports:admin_delete_request`
  - `reports:admin_ai_generate`
- Keep builder URL names stable:
  - `reports:draft_builder`
  - `reports:draft_iterate`
  - `reports:draft_promote`
  - `reports:draft_discard`
- `reports:revoke_share` does not yet exist — the Revoke button in `share_report.html` is rendered disabled with a TODO comment.

### Critical DOM IDs (JS depends on these in admin_queue.html)
The admin queue is a 4-step wizard. All logic is in `window._w` (an object exposing wizard functions). Do not rename IDs without updating both the HTML and the script block:

**Wizard chrome**
- `#queue-main` — scrollable right panel; `scrollTop` reset on step transition
- `#wizard-nav` — sticky bottom nav bar; innerHTML set by `updateNav(n)`
- `#si-1` … `#si-4` — step indicator items (classes: `active`, `done`)
- `#sc-1` … `#sc-3` — step connector bars (class: `done`)

**Step 1 — Review**
- `#notes-textarea` — admin notes; value read by `step1Next()`
- `#parent-sql-display` — readonly textarea (change requests only); parent SQL snapshot; value appended as `existing_sql` on AI generate when non-empty

**Step 2 — Generate**
- `#ai-prompt` — editable AI prompt textarea
- `#gen-error` — inline error alert for AI failures
- `#generate-btn` — Generate SQL button (created dynamically in nav by `updateNav`)
- `#generate-spinner` — spinner inside generate button

**Step 3 — Refine**
- `#sql-editor` — editable SQL textarea; value synced into state on `acceptSQL()`
- `#title-input` — editable suggested title; synced into state on `acceptSQL()`
- `#tags-display` — tag badge container; rendered by `renderTags()`
- `#iter-badge` — iteration counter badge
- `#preview-spinner` — spinner while preview is fetching
- `#preview-error` — warning alert for preview failures
- `#preview-empty` — shown when query returns no rows
- `#preview-wrap` — scrollable table wrapper
- `#preview-table` — the `<table>` element; thead/tbody populated by JS
- `#feedback-textarea` — revision feedback input
- `#revise-btn` — triggers `reviseSQL()` (also wired via `addEventListener`)
- `#revise-spinner` — spinner inside revise button
- `#revise-error` — inline error for revision failures

**Step 4 — Save**
- `#save-title` — report title input (`name=title form=save-form`)
- `#save-tags-display` — tag badge display in step 4
- `#save-sql-preview` — readonly SQL display textarea
- `#save-context` — context notes (`name=context_notes form=save-form`)
- `#save-change` — change notes (`name=change_notes form=save-form`)

**Hidden form**
- `#save-form` — invisible `<form>` element; submit triggered by `type="submit" form="save-form"`
- `#save-sql-hidden` — hidden `name=sql_query` field; set by `acceptSQL()`
- `#save-tags-hidden` — hidden `name=tags` field; set by `acceptSQL()`
- `req-desc-data` — `<script type="application/json">` (via `json_script`) holding description text

**Sidebar**
- `#filter-pills` — container for filter pill badges; pills have `data-filter` attribute

### CSS Scope Classes
- `.reports-hub` — scoped styles on the reports hub page (`hub.html`)
- `.reports-admin-queue` — scoped styles on the admin queue page (`admin_queue.html`)
- Bootstrap 5 Spacelab is the primary styling tool; custom classes supplement only where Bootstrap utilities fall short.

## 10. Forms / Validation Rules
- User request form only accepts plain-language description.
- Admin status form must not allow reverting status to `pending`.
- Share form `shared_with` queryset must be set in view and exclude current user.
- Keep AI tags normalized to lowercase and max 6 server-side.

## 11. Background Tasks / Automation
No Celery/tasks in this app. AI calls are synchronous HTTP requests.

## 12. Testing Expectations
Manual verification after changes:
1. Submit request from hub.
2. Admin queue triage + SQL preview + save version.
3. Run and export a report from hub.
4. Submit change request (owner and non-owner/shared/company contexts).
5. Share flow (`can_branch` on/off).
6. Staff builder flow: create draft, iterate, promote, discard.
7. Permission checks: non-superuser blocked from admin queue; non-staff blocked from builder routes.

## 13. Known Footguns
- Breaking `reports:hub` in `base_template.html` removes global Reports navigation.
- Skipping version creation and writing directly to active SQL breaks immutability guarantees.
- Queryset access checks must include shared/company visibility, not just ownership.
- SQL preview/run/export must always pass through `run_select`.

## 14. Safe Change Workflow
1. Read `reports/CONTEXT.md`.
2. Trace model + form + view + URL + template coupling before edits.
3. Search for URL references before renaming.
4. Keep changes scoped and migration-backed.
5. Run checks and manual flow validation.

## 15. Quick Reference
| Area | Primary files |
|---|---|
| Models | `reports/models.py` |
| Migration baseline | `reports/migrations/0001_initial.py`, `reports/migrations/0002_rebuild.py` |
| Views | `reports/views.py` |
| SQL safety/version helper | `reports/utils.py` |
| Forms | `reports/forms.py` |
| URL routing | `reports/urls.py` |
| Admin registry | `reports/admin.py` |
| User nav coupling | `templates/base_template.html` (`reports:hub`) |
