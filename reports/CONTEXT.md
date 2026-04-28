# Reports Context

## 1. Purpose
`reports` is a reporting workbench with two creation paths:
- request-driven reports (user tickets fulfilled by superusers)
- staff prototype builder drafts (iterative AI-assisted SQL drafting)

The app stores report library items, immutable versions, sharing state, and request workflow.

## 2. App Identity
- Django app name: `reports`
- AppConfig: `ReportsConfig`
- App path: `reports/`
- Classification: feature app integrating report workflow, SQL execution safety, and Anthropic-backed SQL generation

## 3. High-Level Responsibilities
- Manage six-model architecture: `ReportDraft`, `ReportRequest`, `Report`, `ReportVersion`, `ReportShare` plus version lifecycle metadata.
- Provide user hub (`reports:hub`) showing personal reports, company reports, shared reports, and open requests.
- Provide superuser queue workflow for request triage, SQL preview, and version publishing.
- Provide `is_staff` prototype builder flow for draft creation, iteration, promotion, and discard.
- Preserve SQL execution safety via `run_select` and CSV export via `rows_to_csv` from `reports/utils.py`.
- Generate SQL/title/tags JSON using Anthropic `claude-haiku-4-5-20251001` with schema context from `contracts.utils.contracts_schema.generate_db_schema_snapshot()`.

## 4. Key Files and What They Do
- `reports/models.py`: six persistence models with UUID PKs and workflow relations.
  - `ReportDraft`: temporary AI prototype workspace for staff builders.
  - `ReportRequest`: ticket model for requested reports and change requests.
  - `Report`: library object with visibility/source/branch lineage.
  - `ReportVersion`: immutable SQL snapshots with per-report version numbering.
  - `ReportShare`: user-to-user sharing permissions (`can_branch`).
- `reports/views.py`: all user/admin/staff-builder workflows and permission checks.
- `reports/forms.py`: request/change/admin/version/share/draft forms.
- `reports/urls.py`: hub, user actions, admin queue actions, builder actions.
- `reports/admin.py`: admin registrations for all reporting models.
- `reports/utils.py`: SQL safety and execution helpers plus `get_next_version_number`.
- `contracts/utils/contracts_schema.py`: schema snapshot filter/wrapper consumed by reports AI.
- `templates/base_template.html`: global Reports nav now points to `reports:hub`.

## 5. Data Model / Domain Objects
- `ReportDraft`: temporary prompt + iterative SQL/title/tags for `is_staff` builder users; mutable and disposable.
- `ReportRequest`: user ticket lifecycle (`pending`, `in_progress`, `completed`, `change_requested`) with branching hints (`keep_original`, `is_branch_request`) and optional `linked_report`.
- `Report`: runnable report entity in personal/company library; tracks `active_version`, source lineage (`source_request`, `source_draft`, `branched_from`), branching stats (`branch_count`), and run audit (`last_run_at`, `last_run_rowcount`).
- `ReportVersion`: immutable report SQL snapshot with sequential `version_number` scoped per report and optional change/context notes.
- `ReportShare`: per-user share mapping (`report`, `shared_by`, `shared_with`, `can_branch`) with uniqueness per report-recipient pair.

## 6. Request / User Flow
### Requested path
1. Authenticated user submits a request from `reports:hub` (`description`).
2. Superuser processes the request in `reports:admin_queue`.
3. Superuser previews SQL, saves a new `ReportVersion`, and completes the request.
4. If request has `linked_report`, save may update in place or branch depending on `keep_original` / `is_branch_request`.
5. User runs/exports completed reports from hub.

### Prototyped path
1. `is_staff` user starts a draft at `reports:draft_builder`.
2. AI generates first SQL/title/tags; user iterates feedback at `reports:draft_iterate`.
3. User promotes draft to `Report` + `ReportVersion` at `reports:draft_promote`, or deletes draft via `reports:draft_discard`.

## 7. Templates and UI Surface Area
All templates are production-quality Bootstrap 5 (Spacelab theme) UIs. No placeholder templates remain.

### Styling Philosophy
- Bootstrap 5 Spacelab (`spacelab.min.css`) is the primary styling tool — use its full component library.
- Three custom CSS files: `theme-vars.css` (CSS variables), `app-core.css`, `utilities.css`.
- `.btn-outline-brand` is the project's standard outlined brand button for secondary actions.
- Full screen width — hub and admin queue use `container-fluid` / full-viewport layouts.
- Scoped CSS classes: `.reports-hub` on hub page, `.reports-admin-queue` on admin queue page.
- No Tailwind classes in reports templates.

### Template Inventory
- `hub.html` — Main reports library. Full-width, tabbed (My Reports / Company Reports / Shared With Me). Grid/list toggle with localStorage persistence. New Report Request via Bootstrap Offcanvas slide-in from right. Pending Requests collapsible accordion. Request Change via shared Bootstrap modal populated by JS. All report actions always visible (never hover-only).
- `run_results.html` — Report results page. Sticky-header scrollable table. `table-sm table-striped table-hover`. Export CSV + Back to Hub actions. Error alert on failed execution.
- `admin_queue.html` — Full-width two-column layout. Left sidebar (280px, independent scroll) with request list and client-side filter pills. Main area is a **4-step wizard** (one step visible at a time, step indicator bar at top, sticky nav bar at bottom): Step 1 Review & Notes → Step 2 AI Generate → Step 3 Refine SQL (loop) → Step 4 Save. AI calls use fetch to `admin_ai_generate`. Preview uses fetch to `admin_preview_sql_json`. Save form uses HTML5 `form=` attribute pattern with a hidden `<form id="save-form">`. All wizard state lives in `window._w` JS object.
- `draft_builder.html` — Focused single-input page for `is_staff` prototype builder. Centered card, prominent textarea, Generate Report btn-primary btn-lg.
- `draft_iterate.html` — Two-column builder workspace (60/40 split). Left: SQL display (readonly monospace textarea), tags, suggested title, preview results table. Right: collapsible original prompt, feedback form, iteration counter. Full-width bottom action row: Save to My Reports / Discard / Back.
- `share_report.html` — Dedicated share page. Report summary card at top. Share form with native `<select>` for recipient and `can_branch` checkbox. Existing shares list with Revoke button (disabled — TODO: `reports:revoke_share` view not yet implemented).

## 8. Admin / Staff Functionality
- Superusers manage request queue and publish versions.
- `is_staff` users can access prototype builder flow.
- Regular users can submit requests, run/export accessible reports, and request changes.

## 9. Forms, Validation, and Input Handling
- `ReportRequestForm`: user request submission (`description` only).
- `ReportRequestChangeForm`: change request + `keep_original`.
- `AdminReportRequestForm`: superuser-only status/notes updates (cannot set status back to pending).
- `ReportVersionForm`: SQL/context/change notes for immutable version creation.
- `ReportShareForm`: recipient + branch permission (`shared_with` queryset set in view).
- Draft forms for prompt and feedback.
- SQL execution always routes through `run_select` (safety and limit enforcement).

## 10. Business Logic and Services
- AI generation endpoints (`admin_ai_generate`, draft builder calls) require `ANTHROPIC_API_KEY`.
- AI contract returns JSON payload with `sql`, `title`, and `tags`; tags are normalized lowercase and truncated to max 6.
- Version sequencing uses `reports.utils.get_next_version_number`.

## 11. Integrations and Cross-App Dependencies
- Depends on `users` auth model for ownership and sharing FKs.
- Depends on `contracts.utils.contracts_schema.generate_db_schema_snapshot` for AI schema context.
- Mounted through existing `include("reports.urls")` in project URL conf.

## 12. URL Surface / API Surface
| URL name | Path | Purpose |
|---|---|---|
| `reports:hub` | `/reports/` | Main reports hub |
| `reports:submit_request` | `/reports/request/submit/` | Submit new request |
| `reports:run_report` | `/reports/run/<uuid:pk>/` | Run active SQL version |
| `reports:export_report` | `/reports/export/<uuid:pk>/` | Export report CSV |
| `reports:request_change` | `/reports/change/<uuid:pk>/` | Submit change request |
| `reports:promote_to_company` | `/reports/promote/<uuid:pk>/` | Promote personal report to company |
| `reports:share_report` | `/reports/share/<uuid:pk>/` | Share report with another user |
| `reports:admin_queue` | `/reports/admin/` | Superuser request queue |
| `reports:admin_save_version` | `/reports/admin/save/<uuid:pk>/` | Save report version and complete request |
| `reports:admin_preview_sql` | `/reports/admin/preview/<uuid:pk>/` | SQL preview for selected request (full page, legacy) |
| `reports:admin_preview_sql_json` | `/reports/admin/preview-json/<uuid:pk>/` | SQL preview JSON endpoint (returns `{columns, rows}`) used by wizard Step 3 |
| `reports:admin_update_request` | `/reports/admin/update/<uuid:pk>/` | Update request status/notes |
| `reports:admin_delete_request` | `/reports/admin/delete/<uuid:pk>/` | Delete request |
| `reports:admin_ai_generate` | `/reports/admin/ai/generate/` | Superuser AI SQL/title/tags endpoint |
| `reports:draft_builder` | `/reports/build/` | Start draft builder |
| `reports:draft_iterate` | `/reports/build/<uuid:pk>/` | Iterate draft with feedback |
| `reports:draft_promote` | `/reports/build/<uuid:pk>/promote/` | Promote draft into report |
| `reports:draft_discard` | `/reports/build/<uuid:pk>/discard/` | Discard draft |

## 13. Permissions / Security Considerations
- `@login_required` on all routes.
- Admin routes require `_is_admin` (`is_superuser`).
- Builder routes require `_is_staff_builder` (`is_staff`).
- Object access checks:
  - owner can always access
  - company visibility enables org-wide access
  - explicit `ReportShare` grants shared access
- `draft_promote`/`draft_discard` enforce draft ownership.
- SQL safety is centralized in `reports/utils.py`; do not bypass.

## 14. Background Processing / Scheduled Work
No background task framework in this app. AI calls are synchronous request/response.

## 15. Testing Coverage
Automated coverage is minimal; manual verification required for:
- user request flow
- admin queue + version save + preview
- run/export access checks
- share flow
- draft builder iteration/promote/discard flow

## 16. Migrations / Schema Notes
- `0001_initial.py` is retained for migration history consistency.
- `0002_rebuild.py` deletes legacy `ReportRequest` table and creates the new architecture.

## 17. Known Gaps / Ambiguities
- TODO: ReportStar junction table for user favorites/pinning.
- TODO: Embed reports in contextual pages (e.g. supplier detail page passing `supplier_id` as SQL parameter).
