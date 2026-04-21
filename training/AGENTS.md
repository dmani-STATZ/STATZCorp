# AGENTS.md — `training` App

Read `training/CONTEXT.md` before editing. This file defines safe-edit rules specific to the `training` app as implemented.

---

## 1. Purpose of This File

This file guides AI coding agents and developers making changes to the `training` Django app. It identifies what must be reviewed before edits, which files move together, where fragile coupling exists, and what verifications are required after changes.

---

## 2. App Scope

**Owns:**
- CMMC training matrix (`Account` → `Course` via `Matrix`) with frequency-based expiration logic
- Per-user training requirement evaluation and completion tracking (`Tracker`)
- Document upload and streaming for training evidence (`Tracker.document`, `TrainingDoc`)
- Review-click accountability logging (`CourseReviewClick`)
- Arctic Wolf security awareness course management and completion (`ArcticWolfCourse`, `ArcticWolfCompletion`)
- Staff-only audit pages and on-demand PDF exports (`reportlab`)
- Email preview and `.eml` download generation for AW course communications

**Does not own:**
- Core user accounts — depends on `django.contrib.auth.User`
- Navigation shell — `base_template.html` (project-level, not owned by this app)
- Other app models — no other local app imports from `training`

**Classification:** Feature/compliance app. Moderately complex. Contains meaningful business logic in `views.py` without a separate services layer.

---

## 3. Read This Before Editing

### Before changing models
- Read `models.py` fully — particularly `get_frequency_expiration_date`, `Tracker.expiration_date`, `Matrix.FREQUENCY_CHOICES`, and `ArcticWolfCourse.save()` (auto-slug).
- Check `migrations/` — schema has evolved through `0011`; understand the last few migrations before adding fields.
- Read `admin.py` — `TrainingDocInline` attaches to `CourseAdmin`; inline field list must stay aligned with `TrainingDoc` fields.

### Before changing views
- Read the full `views.py` — business logic is concentrated here across ~700+ lines with no separate services module.
- Identify which helpers (`get_completion_status`, `latest_completion_by_matrix`, `pick_strictest_frequency`, `eligible_aw_course_ids_for_user`) are shared across multiple views before modifying them.
- Note that `manage_matrix` only uses `@login_required` — there is **no staff/superuser guard** on the view itself (see Known Footguns).

### Before changing forms
- Read `forms.py` — `CmmcDocumentUploadForm.clean()` enforces user/course validity via `UserAccount` and `Matrix` lookups. Weakening this is a security issue.
- `TrainingDocForm.save()` reads file bytes, derives `file_name` via `get_valid_filename`, and writes a SHA-256 hash — keep these steps aligned.

### Before changing templates
- Confirm all `{% url 'training:...' %}` references still match `urls.py` names.
- `training_base.html` extends `base_template.html` — every training template inherits global nav from the project-level template.
- `manage_matrix.html` contains client-side JS that toggles frequency `<select>` elements when course checkboxes are checked — template and JS must move together if checkbox/select IDs change.
- `admin_cmmc_upload.html` uses `user_course_map_json` injected by the view to disable invalid course dropdowns via JS — changing the context key name breaks the JS.

### Before changing exports/reports
- Read both `training_audit_export` and `arctic_wolf_audit_export` in `views.py` — they use `reportlab` with manual y-coordinate pagination. Changing data shape or status logic requires updating both the HTML audit template and the PDF export.

### Before changing permissions/security
- Confirm `@login_required` is preserved on every view.
- Superuser-only views: `training_audit`, `training_audit_export`, `arctic_wolf_audit`, `arctic_wolf_audit_export`.
- Staff-only view: `admin_cmmc_upload`.
- `review_course_link` validates `UserAccount` membership before streaming files.

---

## 4. Local Architecture / Change Patterns

- **Business logic lives in `views.py`** — there is no `services.py` or `selectors.py`. New logic should be added as module-level helpers in `views.py` (following the existing pattern of `get_completion_status`, `pick_strictest_frequency`, etc.) until the file grows large enough to warrant extraction.
- **Validation belongs in forms** — `CmmcDocumentUploadForm.clean()` and `TrainingDocForm.save()` hold the core upload integrity checks. Do not move these to views or JS.
- **Templates are moderately thin** — they use template tags (`matrix_extras`, `training_filters`) and context dicts assembled in views. The `manage_matrix.html` template is the thickest — it contains JS toggle logic tightly coupled to rendered form field IDs.
- **No signals, no Celery tasks, no async** — all work is synchronous and request-driven. PDF exports are generated on demand, not queued.
- **Admin is functional** — `CourseAdmin` with `TrainingDocInline` is actively used for attaching policy documents to courses. `UserAccountAdmin` restricts user dropdown to active accounts.

---

## 5. Files That Commonly Need to Change Together

### Adding or modifying a `Course` field
`models.py` → migration → `admin.py` (`CourseAdmin`, `TrainingDocInline` field lists) → `forms.py` (`CourseForm`) → `manage_matrix.html` (if rendered in matrix grid) → `training_audit` / `training_audit_export` in `views.py` (if included in audit columns)

### Changing `Matrix.frequency` choices or expiration logic
`models.py` (`FREQUENCY_CHOICES`) → `get_frequency_expiration_date` in `models.py` → `get_completion_status` in `views.py` → `frequency_months` and `pick_strictest_frequency` in `views.py` → `manage_matrix.html` (frequency `<select>` options) → `training_audit` and `training_audit_export` (is_current evaluation) → migration if DB constraint changes

### Adding a new CMMC view
`views.py` (view function) → `urls.py` (named route) → new template extending `training_base.html` → `training_base.html` or `dashboard.html` if a nav link is needed

### Adding a new Arctic Wolf course field
`models.py` (`ArcticWolfCourse`) → migration → `forms.py` (`ArcticWolfCourseForm`) → `admin.py` (if admin-editable) → `arctic_wolf_course_list.html` → `arctic_wolf_audit.html` → `arctic_wolf_audit_export` in `views.py`

### Changing `TrainingDoc` storage
`models.py` → migration → `forms.py` (`TrainingDocForm.save()`) → `admin.py` (`TrainingDocInline` `fields`/`readonly_fields`) → `views.py` (`admin_cmmc_upload`, `review_course_link`, `latest_training_docs_by_course_ids`)

---

## 6. Cross-App Dependency Warnings

### This app depends on
- `django.contrib.auth.User` — every model (`Tracker`, `UserAccount`, `CourseReviewClick`, `ArcticWolfCompletion`) has a FK to `User`. Changing `User` queryset assumptions (e.g., `is_active` filtering) affects form dropdowns and audit views.

### Other apps depend on this app
- **No other local app imports `training` models directly** (confirmed by repo-wide search).
- `templates/base_template.html` (project-level) hard-codes `{% url 'training:dashboard' %}` in the global nav. Renaming or removing the `dashboard` URL name breaks the nav for all apps.
- `templates/index.html` references a `training` tile in the landing page — verify when adding/removing top-level URLs.

### URL name coupling (repo-wide)
The following URL names are referenced outside `training/`:
- `training:dashboard` — `base_template.html` line ~294

Before renaming any URL in `urls.py`, run:
```
grep -r "training:" --include="*.html" --include="*.py" .
```

---

## 7. Security / Permissions Rules

- **Never remove `@login_required`** from any view — all 20+ views require authentication.
- `training_audit`, `training_audit_export`, `arctic_wolf_audit`, `arctic_wolf_audit_export` must check `request.user.is_superuser` at entry. These are inline guards, not decorator-based.
- `admin_cmmc_upload` checks `request.user.is_staff`. Keep this guard.
- `manage_matrix` has **no staff/superuser guard** despite being admin-only in intent. Do not rely on obscurity; consider adding a guard (noted as a known gap in CONTEXT.md).
- `review_course_link` validates `UserAccount` membership before streaming binary file content. Do not bypass this check or widen the queryset.
- `view_document` streams `Tracker.document` binary blobs without ownership check beyond authentication — verify this is acceptable for the threat model before exposing to new user roles.
- `CmmcDocumentUploadForm.clean()` prevents staff from uploading documents for invalid user/course pairs. Do not weaken this validation.
- File uploads use `get_valid_filename` to sanitize names and SHA-256 to hash content. Preserve both.

---

## 8. Model and Schema Change Rules

- `Matrix.is_active` is the soft-delete mechanism — `manage_matrix` sets existing entries to `is_active=False` before creating new ones. Any query that omits `is_active=True` will include stale requirements.
- `Tracker.expiration_date` is a `@property` that calls `get_frequency_expiration_date` — it is not stored in the DB. Do not add a migration for it without removing the property.
- `ArcticWolfCourse.slug` is auto-generated from `name` in `save()`. Changing the slug breaks all AW completion URLs (`/arctic-wolf/complete/<slug>/`) which are distributed to users via email.
- `ArcticWolfCourse.course_id` (UUID) is used to build unguessable links — never reset or modify existing values.
- `TrainingDoc.file_blob` and `Tracker.document` are `BinaryField` columns — no size validation exists. Large uploads grow the DB. Keep this limitation in mind before adding bulk-upload features.
- Before renaming any FK or field used in audit views (`course_id`, `matrix_id`, `account_id`), search `views.py` for direct dict key access patterns (e.g., `user_row["courses"][course.id]`).
- Migrations after `0005` touch document storage and matrix frequency — review them before adding constraints.

---

## 9. View / URL / Template Change Rules

- `app_name = 'training'` is set in `urls.py`. All named routes are namespaced. Use `training:<name>` everywhere.
- The `manage_matrix.html` JS toggles frequency `<select>` elements based on checkbox state. The JS relies on element IDs rendered by the template. If the course loop variable or `id` attribute format changes in the template, the JS breaks silently.
- `admin_cmmc_upload.html` JS uses `user_course_map_json` — a JSON object injected by the view under that exact key name. Renaming this context variable requires updating the template JS.
- `user_requirements.html` iterates `required_courses_data` — a list of dicts assembled in `user_training_requirements`. The dict keys (`matrix_entry`, `completed`, `is_current`, `latest_doc`, `review_outdated`, `tracker_id`, etc.) are used directly in template conditionals. Renaming context keys requires updating the template.
- AW completion URLs use `<slug:slug>` routing. Slugs are generated from course name — renaming a live AW course invalidates distributed completion links.
- `training_base.html` wraps all training templates. If the block structure changes, all child templates must be checked.

---

## 10. Forms / Serializers / Input Validation Rules

- `BaseFormMixin._style_fields()` applies Bootstrap CSS classes to all form widgets automatically. New form fields inherit styling without extra attrs — only override if a specific widget class is needed.
- `CmmcDocumentUploadForm` is a plain `Form` (not `ModelForm`) — it validates the business rule that a user must have an active `Matrix` entry for the course before accepting the upload. This check must not be moved to the view or frontend only.
- `TrainingDocForm.save()` handles file-to-binary conversion, filename sanitization, and SHA-256 hashing. Any change to how `TrainingDoc` stores files must keep `save()`, `admin.py` inline, and the admin upload view in sync.
- There is no serializer layer — this app uses Django forms exclusively.

---

## 11. Background Tasks / Signals / Automation Rules

- **No signals** — confirmed by inspection.
- **No Celery tasks or scheduled jobs** — no `tasks.py`, no `celery` imports.
- **No management commands with business logic** — the `management/` directory contains only `__pycache__` (no command files).
- PDF exports run synchronously in `training_audit_export` and `arctic_wolf_audit_export`. Heavy load will block the request thread.
- AW `.eml` files are generated in-memory via `render_to_string` and the stdlib `email` module — no external mail sending occurs.

---

## 12. Testing and Verification Expectations

**Existing test coverage** (from `tests.py`):
- `CmmcDocumentUploadFormTest` — form validation for valid/invalid user-course combos
- `AdminCmmcUploadViewTest` — staff access, upload/update, context data
- `CmmcDocumentUploadIntegrationTest` — end-to-end upload across account types

**Not tested** (manual verification needed):
- Dashboard CMMC and AW pie chart data
- `user_training_requirements` context assembly and template rendering
- Matrix management (save, deactivate, reactivate)
- Review-click logging (`CourseReviewClick` creation/update)
- AW completion flows and eligibility logic
- PDF audit exports (layout, pagination, color coding)
- Frequency expiration logic under real dates

**After any edit, run:**
```bash
python manage.py test training
```

**Manual smoke tests after significant changes:**
1. Log in as a non-staff user → `/training/` — verify CMMC and AW pie chart counts
2. Visit `/training/requirements/` — verify course list, status badges, upload form
3. Log in as superuser → `/training/audit/` and `/training/audit/export/` — verify PDF renders
4. Visit `/training/matrix/manage/` → select an account → save matrix — verify DB update
5. Visit `/training/admin/cmmc-upload/` as staff → attempt valid and invalid combos

---

## 13. Known Footguns

1. **`manage_matrix` missing permission guard.** The view is `@login_required` only. Any authenticated user who guesses `/training/matrix/manage/` can modify the training matrix for any account. This is confirmed in `CONTEXT.md` as a known gap.

2. **Slug invalidation on AW course rename.** `ArcticWolfCourse.slug` is regenerated on every `save()`. Renaming a course silently breaks all previously distributed completion URLs. There is no redirect or slug history mechanism.

3. **Matrix `is_active` soft-delete pattern.** `manage_matrix` deactivates all current entries for an account before saving the new set. If the POST fails mid-way, the account's matrix is left empty/deactivated. There is no transaction wrapping.

4. **PDF export uses raw y-coordinate pagination.** `training_audit_export` and `arctic_wolf_audit_export` manually track y position. Adding new data columns or rows without adjusting the pagination math causes content to render off-page.

5. **Dashboard queries are O(users × matrix entries).** The `dashboard` view iterates `cmmc_users_with_accounts` in Python with a query per user. This degrades with many users — do not add further per-user loops without profiling.

6. **`view_document` has no ownership check.** Any authenticated user who knows a `tracker_id` can download that document. If `tracker_id` values are sequential integers, this is an IDOR risk.

7. **Template tag name collision.** Both `matrix_extras` and `training_filters` define a `get_item` filter. If both are loaded in the same template, the last `{% load %}` wins. Avoid adding identically named filters.

8. **`user_course_map_json` must be valid JSON.** The `admin_cmmc_upload` view serializes user/course pairs to JSON for frontend JS. If this context key is missing or malformed, the course dropdown will silently fail to filter options.

---

## 14. Safe Change Workflow

1. **Read `training/CONTEXT.md`** for domain background.
2. **Read the relevant local files** — at minimum: `models.py`, the affected view(s) in `views.py`, and matching templates.
3. **Search repo-wide for URL name and context key usage** before renaming anything:
   - `grep -r "training:" --include="*.html" --include="*.py" .`
4. **Make the minimal scoped change.** Identify all files in the coupled cluster (see Section 5) before editing the first one.
5. **Update coupled files together** — model + migration + admin + form + template + export as needed.
6. **Preserve all permission guards** — `@login_required`, superuser checks, staff checks, and object-level access in `review_course_link`.
7. **Run `python manage.py test training`** and fix any failures.
8. **Manually verify** the affected user-facing flow (dashboard, requirements page, audit, or AW completion) in a browser.

---

## 15. Quick Reference

**Primary files to inspect first:**
- `views.py` — all business logic, audit queries, helper functions
- `models.py` — domain objects, `get_frequency_expiration_date`, `ArcticWolfCourse.save()`
- `forms.py` — `CmmcDocumentUploadForm.clean()`, `TrainingDocForm.save()`
- `urls.py` — all named routes under `app_name = 'training'`

**Main coupled areas:**
- Frequency logic: `models.py` ↔ `views.py` ↔ `manage_matrix.html` ↔ audit views
- Document storage: `TrainingDoc` ↔ `TrainingDocForm` ↔ `TrainingDocInline` ↔ `review_course_link` ↔ `admin_cmmc_upload`
- AW completion: `ArcticWolfCourse.slug` ↔ completion URLs ↔ email/eml templates ↔ `eligible_aw_course_ids_for_user`

**Main cross-app dependencies:**
- `base_template.html` hard-codes `training:dashboard` — renaming this URL name breaks global nav
- `auth.User` is referenced in every model and most views

**Security-sensitive areas:**
- `CmmcDocumentUploadForm.clean()` — matrix validation for staff uploads
- `review_course_link` — object-level access check before file streaming
- `view_document` — no ownership check (IDOR risk on tracker_id)
- `manage_matrix` — missing superuser guard

**Riskiest edit types:**
- Renaming `ArcticWolfCourse.name` or modifying `slug` generation
- Changing `Matrix.frequency` choices or expiration math
- Adding columns to audit views without updating PDF export pagination
- Removing or renaming the `dashboard` URL name
- Weakening validation in `CmmcDocumentUploadForm.clean()`


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
