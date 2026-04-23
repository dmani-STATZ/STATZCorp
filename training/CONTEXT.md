# training Context

## 1. Purpose
The `training` app is the compliance training hub inside STATZCorp, pairing account types with required courses (CMMC matrix) and capturing completion evidence, upload documents, and review clicks while offering a parallel Arctic Wolf security awareness workflow that issues unique links, tracks staff completions, and surfaces audits and exports.

## 2. App Identity
- Django app label: `training` (registered via `training.apps.TrainingConfig`).
- Filesystem path: `training/` relative to the repo root.
- Classification: feature/administration app focused on internal compliance reporting and staff training workflow rather than a public API or transactional domain.

## 3. High-Level Responsibilities
- Define and maintain the CMMC training matrix that links `Account` types to `Course`s with `Matrix` entries and frequency toggles (`views.manage_matrix`, `Matrix`, `manage_matrix.html`).
- Provide every user with a dashboard, requirements page, and document upload/mark-complete helpers that reflect their current `Tracker` history (`views.dashboard`, `views.user_training_requirements`, `templates/training/user_requirements.html`).
- Store supporting documentation (`TrainingDoc`, admin inline, `TrainingDocForm`) and track when users click review links (`CourseReviewClick`) for accountability.
- Generate administrative audits and PDF exports for both CMMC and Arctic Wolf programs (`training_audit`, `training_audit_export`, `arctic_wolf_audit`, `arctic_wolf_audit_export`, `reportlab`).
- Manage Arctic Wolf courses, completion links, and communications (course creation, personal course list, email preview/`.eml`, `ArcticWolfCourse`, `ArcticWolfCompletion`).

## 4. Key Files and What They Do
- `models.py`: declares `Course`, `Account`, `Matrix`, `UserAccount`, `Tracker`, `TrainingDoc`, `CourseReviewClick`, `ArcticWolfCourse`, and `ArcticWolfCompletion`; includes helpers such as `get_frequency_expiration_date` and `Tracker.expiration_date`.
- `views.py`: contains the bulk of business logic (dashboard metrics, matrix persistence, requirement rendering, uploads, audits, PDF exports, AW link flows, email helpers, admin uploads, helper functions like `get_completion_status`).
- `forms.py`: supplies `BaseFormMixin`/`BaseModelForm`, forms for `Course`, `Account`, `Matrix`, `ArcticWolfCourse`, and branded `MatrixManagementForm`, `CmmcDocumentUploadForm`, `TrainingDocForm` with styling and validation logic.
- `admin.py`: registers all models, wires `TrainingDocInline` into `CourseAdmin`, and customizes `UserAccountAdmin` to restrict the `user` dropdown to active accounts.
- `urls.py`: exposes the training surface at `/training/` with named routes for dashboards, matrix management, audit/export, AW flows, and uploads.
- `templates/training/`: houses the UI surface (`dashboard.html`, `manage_matrix.html`, `user_requirements.html`, `admin_cmmc_upload.html`, AW templates, `training_base.html`).
- `templatetags/`: `matrix_extras.py` and `training_filters.py` back helper tags used in matrix lists and AW progress bars.
- `tests.py`: includes form tests and integration tests focused on the `CmmcDocumentUploadForm` and `admin_cmmc_upload` path.
- `Docs/`: supporting documentation (`Training App write-up.md`, `databaseOutline.md`) that capture initial requirements and schema intent.

## 5. Data Model / Domain Objects
- `Course`: name, optional link/description, `upload` flag for whether uploads are required in the UI; stringified in admin and `manage_matrix`.
- `Account`: typed choices (`system_admin`, `cui_user`, etc.) describe what training requirements apply; referenced by `UserAccount` and `Matrix`.
- `Matrix`: links `Course` + `Account` with `frequency` choices (`once`, `annually`, `bi-annually`), `is_active` flag introduced later to soft-disable requirements (`views.manage_matrix` reactivates via `update_or_create`).
- `UserAccount`: join table tying Django `User` to `Account`; enforcement occurs in `CmmcDocumentUploadForm` and `views` to determine required Matrix entries.
- `Tracker`: records `User` + `Matrix` completions, optional binary `document`/`document_name`, and exposes `expiration_date` via `get_frequency_expiration_date` so views can highlight stale records.
- `TrainingDoc`: stores binary blobs of submitted course documents along with `file_hash`/`file_date`, surfaced via `TrainingDocInline` in admin and the user review path (`latest_training_docs_by_course_ids`).
- `CourseReviewClick`: logs first/last click times and the referenced `TrainingDoc`, enforcing a per-user/per-matrix unique constraint for review accountability (`views.review_course_link`).
- `ArcticWolfCourse`: name, description, auto-slug, and unique `course_id` (UUID) generated to build unguessable AW links; new courses surface via `add_arctic_wolf_course` and listing views.
- `ArcticWolfCompletion`: unique `(user, course)` completion records with optional `completed_date`; used in AW completion, audit, and chart flows.

## 6. Request / User Flow
1. **Dashboard (`/training/`)**: `views.dashboard` aggregates user-specific CMMC completions, global pie-chart stats (Chart.js in `dashboard.html`), and enables superusers to jump to audits, matrix, or document uploads.
2. **Matrix management**: `manage_matrix` shows `Account` selector, checkboxes for `Course`s, per-course `frequency` dropdowns, and persists selections via `Matrix.objects.update_or_create`; `manage_matrix.html` enables JS that toggles frequency selects when courses are chosen.
3. **User requirements**: `user_training_requirements` builds `required_courses_data` combining latest `Tracker`, deadline logic, latest `TrainingDoc`, and `CourseReviewClick`; template highlights expired/completed courses, exposes a review link, file upload controls (`upload_document`), and a `mark_complete` form.
4. **Review/document flows**: `review_course_link` enforces that the request user is tied to the matrix’s account before streaming the latest file or redirecting to an external `link`; `upload_document`/`view_document` manage binary storage and retrieval of supporting docs.
5. **Audits & exports**: `training_audit` and `arctic_wolf_audit` compute row/column summaries of required training per user, while `training_audit_export` and `arctic_wolf_audit_export` render PDFs via `reportlab` using the same datasets for printable reports.
6. **Arctic Wolf journeys**: superusers can add new AW courses (`add_arctic_wolf_course`), view the list (copyable link, email preview/.eml), and staff/users complete them via slugged URLs (`arctic_wolf_training_completion`, `arctic_wolf_complete_training`, `user_arctic_wolf_courses`). Completion eligibility honors the `User.date_joined` vs course `created_at` via `eligible_aw_course_ids_for_user`.
7. **Admin uploads**: `admin_cmmc_upload` uses `CmmcDocumentUploadForm`, a JSON map of user-course assignments, and a filtered dropdown so staff can only upload for valid matrix entries; success creates or updates `Tracker` records and reflects recent uploads in a datatable.

## 7. Templates and UI Surface Area
- `training_base.html`: lightweight wrapper that extends `base_template.html`, so every training template inherits shared navigation/JS blocks.
- `dashboard.html`: two-column layout with Chart.js pie charts, status cards, admin action buttons, and links to requirements/AW screens.
- `user_requirements.html`: lists required courses, colored status bars, mark-complete buttons, inline document upload forms, and review link sections.
- `manage_matrix.html`: account selector, grid of checkboxes, frequency dropdowns, and client-side JS that toggles frequency selects when courses are chosen.
- `admin_cmmc_upload.html`: staff-only form with user/course dropdowns, file upload, helper text checklist, and a table of recent tracker uploads powered by the `user_course_map_json` provided by the view.
- AW templates (`arctic_wolf_course_list.html`, `arctic_wolf_completion.html`, `arctic_wolf_completion_status.html`, `user_arctic_wolf_courses.html`, `arctic_wolf_audit.html`, `arctic_wolf_email.html`, `arctic_wolf_email_body.html`): progress bars, copy-to-clipboard controls, email previews, and completion buttons tailored to unique AW links.
- Template tags: `matrix_extras` (helpers to locate matrix entries by course id) and `training_filters` (percentage helper used in AW progress bars).

## 8. Admin / Staff Functionality
- `admin.py` registers every model, uses `TrainingDocInline` to let admins attach supporting docs to `Course`s, and customizes `UserAccountAdmin` to limit the `user` field to active accounts.
- `manage_matrix`, `training_audit`, `training_audit_export`, `admin_cmmc_upload`, and AW audit/export views surface only for staff or superusers (guards inside views enforce `request.user.is_staff`/`is_superuser`).
- Staff pathways also include the dashboard admin action buttons (visible when `request.user.is_superuser`).

## 9. Forms, Validation, and Input Handling
- `BaseFormMixin` applies consistent Bootstrap-esque classes (`form-input`, `form-select`, etc.) and auto-placeholder text to every field.
- Model forms (`CourseForm`, `AccountForm`, `MatrixForm`, `ArcticWolfCourseForm`) expose the expected fields to admin UIs; `MatrixForm` is used in admin registration.
- `MatrixManagementForm` wraps the account selector used in the matrix page and disallows empty selection.
- `CmmcDocumentUploadForm` lets staff upload supporting docs only when the chosen user has an active `Matrix` entry for the chosen course; its `clean` raises `ValidationError` for invalid combos, and it limits course dropdowns via `UserAccount` lookup.
- `TrainingDocForm` requires a file on create, reads the uploaded bytes into `file_blob`, derives a sanitized name via `get_valid_filename`, and stores a SHA-256 hash (`file_hash`).

## 10. Business Logic and Services
- Helper functions in `views.py` such as `get_completion_status`, `latest_completion_by_matrix`, `latest_training_docs_by_course_ids`, `eligible_aw_course_ids_for_user`, and `pick_strictest_frequency` keep the dashboard/audit logic DRY.
- `dashboard` computes per-user progress percentages, total vs completed counts, and provides context for both CMMC and AW pie charts.
- `user_training_requirements` assembles per-course metadata (completion flag, expiration date, document links, review status) so templates can highlight what to act on.
- `training_audit`/`arctic_wolf_audit` iterate through users/courses to feed the printable exports with row-wise completion data, grouping by accounts and evaluating `is_current` states.
- Document flows (`review_course_link`, `mark_complete`, `upload_document`, `view_document`) ensure only associated users can mark courses, upload attachments, and retrieve stored binary data.
- Admin upload logic (`admin_cmmc_upload`) builds `user_course_map_json` so JavaScript can disable invalid course selections, then creates/updates `Tracker` rows and surfaces recent uploads.
- AW helpers control which courses are required based on `User.date_joined`, maintain completion records via `get_or_create`, and build email previews/`.eml` downloads using `render_to_string` plus the standard library `email` builders.
- Exports (`training_audit_export`, `arctic_wolf_audit_export`) render PDFs on demand with `reportlab`, manual pagination, and color-coded status indicators.

## 11. Integrations and Cross-App Dependencies
- `STATZWeb/urls.py` includes `path('training/', include('training.urls'))`, so `/training/` is mounted alongside other feature apps.
- Base navigation (`templates/base_template.html`) adds a “Training” link that points to `training:dashboard`, and the landing page config (`templates/index.html`) references a `training` tile, so other templates assume training exists.
- The app depends on Django's built-in `auth.User` (imported in `models.py`, `views.py`, `forms.py`, `tests.py`), so every training record connects back to the central user table.
- No other app currently imports `training` models, so the primary integration points are the shared URLs/nav and the common `User` entity.

## 12. URL Surface / API Surface
- `/training/` -> `views.dashboard`: user overview with CMMC and AW metrics, Chart.js data, and admin quick links.
- `/training/audit/` & `/training/audit/export/` -> CMMC audit list and PDF export (superuser-only).
- `/training/matrix/manage/` -> `manage_matrix`: account/course matrix workflow with dynamic frequency selects.
- `/training/requirements/` -> `user_training_requirements`: lists requirements, uploads, mark-complete actions.
- `/training/requirements/review/<matrix_id>/` -> `review_course_link`: logs clicks and streams the latest `TrainingDoc` or external link.
- `/training/mark-complete/<course_id>/` -> `mark_complete`: creates `Tracker` rows for the authenticated user.
- `/training/upload-document/<matrix_id>/` & `/training/view-document/<tracker_id>/` -> user-level document upload/download handlers.
- `/training/arctic-wolf/add/`, `/list/`, `/complete/<slug>/`, `/complete/<slug>/submit/`, `/my-courses/`, `/audit/`, `/audit/export/`, `/email/<slug>/`, `/email/<slug>/download.eml` -> Arctic Wolf management, completion, audit, and communication flows.
- `/training/admin/cmmc-upload/` -> `admin_cmmc_upload`: staff-only upload interface backed by `CmmcDocumentUploadForm`.

## 13. Permissions / Security Considerations
- All views are decorated with `@login_required` and therefore require authentication.
- `training_audit`, `training_audit_export`, `arctic_wolf_audit`, and `arctic_wolf_audit_export` short-circuit if `request.user.is_superuser` is false.
- `admin_cmmc_upload` requires `request.user.is_staff`, and the form validation ensures only valid user/course pairs can submit documents.
- `review_course_link` verifies the viewer has a `UserAccount` link to the matrix's account before streaming documents or redirecting to `Course.link`.
- File uploads use `get_valid_filename` and store SHA-256 hashes, while `view_document`/`review_course_link` stream binary content with `Content-Disposition` headers to limit exposure.

## 14. Background Processing / Scheduled Work
There are no asynchronous workers or scheduled jobs. Every report or export runs synchronously in the triggered view (e.g., `training_audit_export`, `arctic_wolf_audit_export` build PDFs on demand with `reportlab`).

## 15. Testing Coverage
`tests.py` includes:
1. `CmmcDocumentUploadFormTest`: verifies validation logic (valid/invalid combos, active-user filtering, required fields).
2. `AdminCmmcUploadViewTest`: checks staff access, document uploads/updates, redirects, and context data for recent uploads.
3. `CmmcDocumentUploadIntegrationTest`: runs comprehensive upload scenarios across account types/courses and ensures invalid combos are rejected.
Current coverage stops short of dashboards, AW flows, audit exports, and user requirement templates.

## 16. Migrations / Schema Notes
`training/migrations/` shows step-by-step schema evolution:
- `0001_initial` starts with the core training tables.
- `0002_useraccount` adds the `UserAccount` link.
- `0003` & `0004` add `ArcticWolfCourse` metadata (`created_at`, `slug`).
- `0005_course_upload` and `0006_alter_tracker_document` extend `Course`/`Tracker` for upload flags and documents.
- `0007_coursereviewclick` through `0011_training_docs` add `CourseReviewClick`, weekly frequency fields, `is_active`, and the separate `TrainingDoc` storage used by admin/time-stamped review text.
When modifying schema fields, review migrations after `0005` to avoid inconsistencies (especially `Matrix.frequency`, `Tracker.document`, and the new `TrainingDoc` table).

## 17. Known Gaps / Ambiguities
- `manage_matrix` lacks a hard `is_staff`/`is_superuser` guard even though the UI exposes it only to superusers; consider adding one to prevent unauthorized access when a non-admin guesses the URL.
- AW email preview and `.eml` routes require only authentication rather than a staff role, so confirm whether any authenticated user should be able to generate those drafts.
- Document uploads keep binary blobs in the database without any size validation; large uploads may grow the `Tracker.document`/`TrainingDoc.file_blob` blobs unexpectedly.
- The client-side course filtering in `admin_cmmc_upload` assumes `user_course_map_json` contains entries for every user; if matrix data is stale, the dropdown may disable all options without clarifying which requirement is missing.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- Search the repo for `training:` before renaming URLs because templates (`base_template.html`, `dashboard.html`, AW emails) rely on the named routes.
- When touching frequency logic, update `get_frequency_expiration_date`, `Matrix.FREQUENCY_CHOICES`, and all audit/dashboard helpers that depend on the `is_current` calculation.
- Any change to document storage must keep `TrainingDocForm`, `TrainingDocInline`, `upload_document`, `admin_cmmc_upload`, and the review link logic aligned so uploads remain discoverable.
- The AW eligibility helper (`is_aw_course_required_for_user`) compares `course.created_at` to `User.date_joined`; adjust it with care to avoid accidentally including/excluding staff from audits.
- Because `views.py` contains many helpers, split future logic into smaller helpers/services before editing, and coordinate template updates when altering context structure.

## 19. Quick Reference
- **Primary models:** `Course`, `Account`, `Matrix`, `UserAccount`, `Tracker`, `TrainingDoc`, `CourseReviewClick`, `ArcticWolfCourse`, `ArcticWolfCompletion`.
- **Main URLs:** `/training/`, `/training/requirements/`, `/training/matrix/manage/`, `/training/audit/`, `/training/admin/cmmc-upload/`, `/training/arctic-wolf/...` paths, `/training/upload-document/<matrix_id>/`, `/training/view-document/<tracker_id>/`.
- **Key templates:** `training/dashboard.html`, `training/user_requirements.html`, `training/manage_matrix.html`, `training/admin_cmmc_upload.html`, `training/arctic_wolf_course_list.html`, `training/training_audit.html`, `training/arctic_wolf_audit.html`, `training/arctic_wolf_email.html`/`_body.html`.
- **Key dependencies:** Django `auth.User`, Chart.js (dashboard), `reportlab` (PDF exports), custom template tags in `templatetags/`, and designer docs in `training/Docs/`.
- **Risky files to review first:** `views.py` (heavy logic), `templates/training/*.html` (hard-coded links/JS), `forms.py` (upload validation), and migrations `0005`+ (schema changes for documents and matrix frequency).








## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
