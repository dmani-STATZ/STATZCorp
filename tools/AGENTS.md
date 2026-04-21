# AGENTS.md — `tools` App
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

Read `tools/CONTEXT.md` first. This file defines safe-edit rules for AI coding agents and developers modifying the `tools` app. It does not duplicate `CONTEXT.md`; it complements it with actionable guidance.

---

## 1. Purpose of This File

This file tells a coding agent how to modify the `tools` app safely. It identifies fragile coupling, security-sensitive patterns, and verification steps specific to this app as it actually exists in the repository.

---

## 2. App Scope

**Owns:**
- The `/tools/` URL surface and all four endpoints: `index`, `merge_pdfs`, `delete_pages`, `split_pdf`
- All PDF processing logic (`PdfReader`/`PdfWriter` via `pypdf`)
- The single-page UI in `templates/tools/pdf_merger.html` with all its inline JavaScript

**Does not own:**
- Authentication — delegates entirely to `@login_required` from Django's `auth` framework
- Global navigation — the "PDF Merger" nav link lives in `templates/base_template.html:317`, outside this app
- No models, no persistent data, no admin, no migrations, no signals, no tasks

This is a **self-contained utility app**. It is thin in structure but non-trivial in its inline JavaScript and binary-handling logic.

---

## 3. Read This Before Editing

**Before changing view logic (`views.py`):**
- Read all of `tools/views.py` — all business logic is concentrated here
- Understand `_parse_page_ranges` before touching `delete_pages` or `split_pdf`; both callers depend on its `ValueError` exception contract
- Check the three limit constants (`MAX_FILES`, `MAX_FILE_SIZE_BYTES`, `MAX_TOTAL_SIZE_BYTES`) — they must stay in sync with the client-side limit warnings in `templates/tools/pdf_merger.html`

**Before changing the template (`templates/tools/pdf_merger.html`):**
- Read the full inline `<script>` block — it contains all UI state, CSRF handling, fetch URLs, button enabling/disabling logic, and error display
- Locate `mergeUrl`, `deleteUrl`, `splitUrl` — these are hardcoded via `{% url %}` tags; any URL name change in `urls.py` must be reflected here immediately
- Confirm button IDs (`exportBtn`, `deletePagesBtn`, `splitPdfBtn`, `clearBtn`, `uploadTrigger`, `fileInput`, `dropZone`, `pageRanges`) — the script wires all behavior by these IDs

**Before changing `urls.py`:**
- Check `templates/tools/pdf_merger.html` for all three `{% url 'tools:...' %}` references
- Check `templates/base_template.html:317` for `{% url 'tools:index' %}` — this is the only external reference to this app's URLs and it lives in the global nav template

**Before touching encryption or `pypdf` API:**
- Read the `reader.decrypt("")` pattern used identically in all three POST views — changes must be applied consistently

---

## 4. Local Architecture / Change Patterns

- **No service layer.** All business logic is directly in `views.py`. Do not introduce a `services.py` without moving all three PDF functions there together.
- **No forms layer.** Input is read directly from `request.FILES` and `request.POST`. Validation is manual, in-view.
- **Template-heavy JS.** The entire UI behavior is in an inline `<script>` block inside `pdf_merger.html`. There are no external JS files for this app. Changes to UI logic go in that script block.
- **Utility function `_parse_page_ranges` is shared internally.** It is called by both `delete_pages` and `split_pdf`. Do not change its signature or exception behavior without updating both callers.
- **Binary streaming pattern.** All three POST views use `BytesIO` + `HttpResponse` with `Content-Disposition` attachment headers. Keep this pattern intact when adding new endpoints.

---

## 5. Files That Commonly Need to Change Together

| Change | Files to update together |
|---|---|
| Add a new PDF operation endpoint | `views.py` + `urls.py` + `templates/tools/pdf_merger.html` (new `{% url %}` + JS fetch call + button) |
| Change a URL name | `urls.py` + `pdf_merger.html` inline JS + `templates/base_template.html` (if `tools:index` is affected) |
| Change upload limits | `views.py` constants (`MAX_FILES`, `MAX_FILE_SIZE_BYTES`, `MAX_TOTAL_SIZE_BYTES`) + client-side limit warnings in `pdf_merger.html` |
| Change `_parse_page_ranges` signature or exceptions | `views.py` (both `delete_pages` and `split_pdf` callers) |
| Change response filename (`merged.pdf`, `modified.pdf`, `split_parts.zip`) | `views.py` `Content-Disposition` header + any documentation/user-facing text in the template |

---

## 6. Cross-App Dependency Warnings

**This app depends on:**
- `templates/base_template.html` — template inheritance; the PDF Merger page uses `{% extends 'base_template.html' %}` and `{% block body %}`
- Django's `auth` framework — `@login_required` protects all views
- `pypdf==6.7.1` — the only external library; pinned in `requirements.txt`; API changes on upgrade will break views

**Other apps that depend on this app:**
- `templates/base_template.html` line 317 contains `{% url 'tools:index' %}` — this is the global nav reference. Renaming or removing the `index` URL name breaks the navigation for the entire site.
- No other app imports from `tools`, uses its models, or reverses its URLs (confirmed by repo search)

**Key constraint:** The only cross-app surface is the `tools:index` URL name referenced in the shared nav. Treat it as load-bearing.

---

## 7. Security / Permissions Rules

- All four views carry `@login_required`. Do not remove or weaken this decorator on any view, including any new endpoints added.
- The three POST views also carry `@require_POST`. Do not remove this — it prevents accidental GET-based file access.
- All `fetch` calls in the template extract the CSRF token from the `csrftoken` cookie and send it as `X-CSRFToken`. If CSRF handling in the template changes, verify the `fetch` headers still attach the token.
- The app accepts user-submitted binary file data. The size limits (`MAX_FILES`, `MAX_FILE_SIZE_BYTES`, `MAX_TOTAL_SIZE_BYTES`) are the primary DoS protection. Do not raise them without understanding memory implications.
- Encrypted PDF handling: the code tries `reader.decrypt("")` (empty password). If this fails, it returns HTTP 400. Do not silently swallow decryption failures.
- File extension check (`.pdf` suffix only) is the sole content-type gate. There is no MIME sniffing. If you strengthen this, update the front-end `accept="application/pdf"` attribute and the server validation together.

---

## 8. Model and Schema Change Rules

**No models exist in this app.** `tools/models.py` is empty. There are no migrations except `__init__.py`. There is no persistent data.

Do not add models to this app without a deliberate architectural decision. If a model is added:
- Create and apply a migration
- Register in `admin.py` if staff need visibility
- Update `CONTEXT.md` and this file

---

## 9. View / URL / Template Change Rules

- **Do not rename `tools:index`, `tools:merge_pdfs`, `tools:delete_pages`, or `tools:split_pdf`** without updating both `templates/tools/pdf_merger.html` and `templates/base_template.html` simultaneously.
- The template's `mergeUrl`, `deleteUrl`, and `splitUrl` JS constants are resolved server-side via `{% url %}` tags at lines 102–104 of `pdf_merger.html`. They are not configurable at runtime.
- The `iframe` preview uses `URL.createObjectURL` on in-memory `File` objects. If a new endpoint returns a file, follow the same pattern as the existing download flows (blob fetch → `<a>` click).
- `{% block body %}` and `{% block extra_scripts %}` are the two template blocks used. If `base_template.html` renames these blocks, the tool page will silently break.
- Context key `title` is passed by `pdf_merger` view — verify it is used in `base_template.html` if the title display changes.

---

## 10. Forms / Serializers / Input Validation Rules

No Django forms or serializers are used. All validation is manual in each view function.

Rules:
- Do not add a form class without also removing the equivalent manual validation from the view — do not duplicate.
- `_parse_page_ranges` is the shared range parser. It raises `ValueError` on any invalid input; callers catch `ValueError` and return `JsonResponse` with HTTP 400. Preserve this contract.
- If you add a new input field, update: the HTML input in `pdf_merger.html`, the JS fetch body, and the view's `request.POST.get(...)` / `request.FILES.get(...)` read — all three must stay consistent.

---

## 11. Background Tasks / Signals / Automation Rules

**None.** There are no Celery tasks, signals, management commands, scheduled jobs, or async processing in this app. All behavior is synchronous and request-scoped.

---

## 12. Testing and Verification Expectations

`tools/tests.py` is empty. There are no automated tests.

After any edit, manually verify:

1. **Upload and merge**: upload 2–3 PDFs, click "Export file", confirm a valid merged PDF downloads
2. **Delete pages**: upload a multi-page PDF, enter a valid range, click "Delete pages", confirm modified PDF downloads with correct pages removed
3. **Split to ZIP**: upload a multi-page PDF, click "Split to ZIP" (no range = one-per-page), confirm ZIP downloads with correctly named `part_N.pdf` files
4. **Validation paths**: upload a non-PDF file and confirm a user-visible error message appears; enter an out-of-range page number and confirm error
5. **Navigation**: confirm the "PDF Merger" link in the global nav still resolves correctly after any URL change
6. **Unauthenticated access**: confirm `/tools/` and `/tools/merge/` redirect to login when not authenticated

If tests are added, place them in `tools/tests.py` and target `merge_pdfs`, `delete_pages`, `split_pdf`, and `_parse_page_ranges` directly.

---

## 13. Known Footguns

- **Renaming `tools:index` breaks global nav.** `base_template.html:317` references it. A URL rename that passes local tests will still break site-wide navigation silently.
- **Limit constants duplicated in front-end.** `MAX_FILES=20`, `MAX_FILE_SIZE_BYTES=25MB`, `MAX_TOTAL_SIZE_BYTES=100MB` appear in both `views.py` and the template's descriptive text. Changing one without the other creates misleading UX (e.g., the UI says "25 MB each" but the server now rejects at 10 MB).
- **`_parse_page_ranges` ValueError contract.** Both `delete_pages` and `split_pdf` rely on catching `ValueError` from this function. If you refactor it to return `None` or log errors instead, both callers silently pass invalid ranges through.
- **`split_pdf` re-parses the range string.** The view calls `_parse_page_ranges` once for validation, then re-parses the raw string a second time with a manual loop to build `parts`. These two parsing passes must stay consistent — a divergence causes silent wrong-page splits.
- **`pypdf` version pinned at 6.7.1.** The `PdfReader`, `PdfWriter`, `PdfReadError`, and `reader.decrypt` API surface are pinned. Upgrading `pypdf` requires re-validating all three views against the new API.
- **No MIME sniffing.** Only `.endswith(".pdf")` (case-insensitive) is checked. A renamed non-PDF file can pass validation and cause `PdfReadError`. The current error handling catches this, but it's worth knowing the gate is shallow.
- **Inline JS has no unit tests.** UI behavior (drag-drop, reorder, preview, CSRF, blob download) is entirely in the template script block with no coverage.

---

## 14. Safe Change Workflow

1. Read `tools/CONTEXT.md` for full behavioral context
2. Read the specific view function(s) in `tools/views.py` you intend to change
3. Read `templates/tools/pdf_merger.html` — especially lines 100–end (the `<script>` block) — before touching anything URL- or input-related
4. Search `templates/base_template.html` for any `tools:` URL reversal before renaming URL names
5. Make minimal, scoped changes
6. If limits changed: update both `views.py` constants and template descriptive text
7. If URL names changed: update `urls.py`, `pdf_merger.html` `{% url %}` tags, and `base_template.html`
8. If `_parse_page_ranges` changed: verify both `delete_pages` and `split_pdf` callers still work
9. Manually verify the five flows listed in Section 12
10. Note: there are no automated tests to run — manual verification is the only gate

---

## 15. Quick Reference

| | |
|---|---|
| **Primary files** | `tools/views.py`, `templates/tools/pdf_merger.html`, `tools/urls.py` |
| **Shared utility** | `_parse_page_ranges` in `views.py` — used by two views |
| **Cross-app surface** | `templates/base_template.html:317` — `tools:index` in global nav |
| **External dependency** | `pypdf==6.7.1` in `requirements.txt` |
| **Security gates** | `@login_required` + `@require_POST` on all non-UI views; CSRF via cookie in JS |
| **No models** | No migrations, no admin, no persistent state |
| **Riskiest edits** | Renaming URL names, changing `_parse_page_ranges`, upgrading `pypdf`, modifying upload limits |
| **Biggest blind spot** | No automated tests; all verification is manual |


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
