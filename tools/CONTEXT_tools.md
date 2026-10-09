# Tools Context

## 1. Purpose
- Hosts the PDF utility surface under `/tools/` so authenticated staff can merge uploaded PDFs, strip pages, or split a single document into multiple parts without leaving the Django site. Evidence: `tools/urls.py` routes `""`, `"merge/"`, `"delete-pages/"`, and `"split/"` to the corresponding views in `tools/views.py`, and `STATZWeb/urls.py` mounts `tools.urls` at `path("tools/", ...)`.
- Supplies the JavaScript-heavy UX found in `templates/tools/pdf_merger.html` plus its inline script so users can drag/drop files, reorder them, preview a selection, and drive the back-end endpoints with CSRF-protected fetch calls.

## 2. App Identity
- Django app name: `tools`.
- AppConfig: `ToolsConfig` defined in `tools/apps.py` with `default_auto_field = 'django.db.models.BigAutoField'`.
- Filesystem path: `tools/`.
- Role: support/utility tool delivering desktop-like PDF helpers from the main site layout (`pdf_merger.html` extends `base_template.html`), so treat it as a small staff-facing feature app rather than a core transactional domain.

## 3. High-Level Responsibilities
- Render `tools/pdf_merger.html` via the `pdf_merger` view so authenticated users get the dropzone/list/preview UX described in the template.
- Validate uploads on the server (count, per-file size, combined size, `.pdf` suffix, decryptability) before fiduciary actions; this prevents oversized or malformed files from reaching `pypdf`.
- Merge files sequentially through `PdfReader`/`PdfWriter` and return a single downloadable attachment (`merged.pdf` for `merge_pdfs`).
- Strip user-specified pages while preserving at least one page (`delete_pages`) and return the cleaned file as `modified.pdf`.
- Split a single PDF into parts defined by ranges (falling back to one-per-page) and bundle the outputs into `split_parts.zip`.
- Provide the front-end wiring that sends selected files, range strings, and CSRF tokens to these views (`templates/tools/pdf_merger.html` inline script).

## 4. Key Files and What They Do
- `apps.py`: declares `ToolsConfig`; used on `INSTALLED_APPS` (see `STATZWeb/settings.py` line 85) so Django recognizes the module.
- `urls.py`: exposes `tools:index`, `tools:merge_pdfs`, `tools:delete_pages`, and `tools:split_pdf`; all endpoints live at `/tools/` after the project-level include.
- `views.py`: contains the UI view plus three POST-only helpers that call `pypdf` (see `requirements.txt`), enforce `MAX_FILES`/`MAX_FILE_SIZE_BYTES`/`MAX_TOTAL_SIZE_BYTES`, decrypt encrypted files, parse range strings via `_parse_page_ranges`, build `PdfWriter` output, and emit `HttpResponse` downloads or `JsonResponse` errors.
- `templates/tools/pdf_merger.html`: server-rendered page with drag-and-drop file input, file list with reorder/delete controls, preview iframe, range input, action buttons, status banner, and the inline script that talks to the view endpoints.
- `services/scan_inbox_graph.py`: Microsoft Graph client for the scan mailbox (GCC High, immutable message IDs).
- `services/scan_inbox_queue.py`: pending PDF queue and mail-folder sweep.
- `services/scan_inbox_search.py`: dash-insensitive contract search (company-scoped).
- `services/scan_inbox_destination.py`: read-only SharePoint folder resolution (strict Graph GETs; no `drive_item_lookup`).
- `services/scan_inbox_sharepoint.py`: **only** SharePoint writer for Scan Inbox (`conflictBehavior=fail`).
- `services/scan_inbox_filing.py`: file/skip orchestration and append-only audit rows.
- `models.py`: `ScanFilingLog` (`tools_scan_filing_log`), append-only filing audit.
- `management/commands/scan_inbox_probe.py`: Stage 0 mailbox probe (optional `--test-write`).
- `management/commands/scan_inbox.py`: Stage 1 CLI (`list`, `search`, `destination`, `file`, `skip`, `sweep`, `log`).
- `tests/test_scan_inbox_probe.py`, `tests/test_scan_inbox_stage1.py`: mocked Graph/SharePoint tests.

## 5. Data Model / Domain Objects
- **`ScanFilingLog`** (`tools_scan_filing_log`): append-only audit of filed, skipped, and failed scan PDFs. Application code only calls `ScanFilingLog.objects.create()`. Read-only in Django admin.
- PDF merge/split/delete remains stateless (no models for that UI).

## 6. Request / User Flow
- Entry point: `/tools/` (via `STATZWeb/urls.py`) calls `tools.views.pdf_merger`, which renders `templates/tools/pdf_merger.html`.
- The page lets users upload up to 20 PDFs (client-side `MAX_FILES`), reorder them, preview the selected file in an `iframe`, and type ranges for delete or split operations.
- Clicking “Export file” submits the queued files via `fetch` to `tools:merge_pdfs`; on success the browser downloads `merged.pdf`.
- “Delete pages” and “Split to ZIP” send the selected file plus the `pageRanges` text to `tools:delete_pages` or `tools:split_pdf`; the server parses the comma-separated ranges (`_parse_page_ranges`), validates them, and returns either a single PDF or a ZIP as attachments.
- Status messages, button disabling, and CSRF tokens are managed entirely by the inline script, so the view expects POST bodies with file data (multi-part) and rejects empty uploads or invalid ranges with JSON errors.

## 7. Templates and UI Surface Area
- Template path: `templates/tools/pdf_merger.html` (extends `base_template.html`), so it inherits the global navigation/layout from the project while providing only this tool’s content block.
- UI components: header with description, buttons for merging/deleting/splitting/clearing, drag-and-drop zone with hidden native `<input>`, ordered file list with action buttons (reorder/delete), preview pane with `iframe`, range input, and status banner.
- Inline `<script>` (inside `{% block extra_scripts %}`) encapsulates logic for uploads, drag/drop, UUID generation, preview updates (`iframe.src`), file reordering events, exporting, deleting, splitting, CSRF token extraction, and dynamic status messaging. There are no separate static JS assets; the behavior lives entirely inside this template.
- The UI relies on Bootstrap-esque utility classes defined in the overarching project styles; no app-specific static files exist under `tools/static`.

## 8. Admin / Staff Functionality
- No models are registered in `admin.py`, so Django admin offers nothing for this app. All staff interactions happen through the `/tools/` UI.

## 9. Forms, Validation, and Input Handling
- The view functions do not use Django `forms`/`formsets`; instead they read `request.FILES`/`request.POST` directly and return `JsonResponse` errors when validation fails.
- Shared validations: `MAX_FILE_SIZE_BYTES` (25 MB) per upload, `MAX_TOTAL_SIZE_BYTES` (100 MB) per merge session, `MAX_FILES` (20 files); only files ending with `.pdf` are permitted.
- `_parse_page_ranges(range_str, total_pages)` enforces numeric, ascending ranges that stay within `total_pages` and throws `ValueError` when the input is malformed; callers translate that into user-facing JSON errors.
- `delete_pages` enforces at least one page remains and that the range list is non-empty; `split_pdf` treats empty ranges as “split every page” but still validates ranges if provided.
- All POST endpoints require `@login_required` plus `@require_POST` so the front-end must send CSRF tokens (the script gathers `csrftoken` from cookies and attaches it to `fetch` headers).

## 10. Business Logic and Services
- `merge_pdfs`: iterates uploaded files, enforces limits, reads them with `PdfReader`, decrypts encrypted files by trying an empty password, appends every page to a shared `PdfWriter`, and streams a single PDF back.
- `delete_pages`: builds a `remove_indexes` set from `_parse_page_ranges`, refuses to delete everything, adds remaining pages to `PdfWriter`, and returns `modified.pdf`.
- `split_pdf`: reuses `_parse_page_ranges` and, when ranges are provided, re-parses the raw strings to honor spans; for each part it writes a `part_{idx}.pdf` and bundles them into a ZIP using `zipfile.ZipFile` with `ZIP_DEFLATED`.
- `_parse_page_ranges`: utility that accepts strings like `1,3,5-7`, guards against non-digit tokens, enforces 1-based numbering, and returns sorted zero-based indexes used by both delete and split flows.
- Error handling: every major branch returns a `JsonResponse` with a helpful message (size issues, invalid file, invalid range, encryption failure) before the view attempts to stream binary data.

## 11. Integrations and Cross-App Dependencies
- Project URL wiring (`STATZWeb/urls.py`) mounts this app at `/tools/`, so any navigation/menu that exposes `/tools/` relies on that include.
- Template extends the shared `base_template.html`, which supplies styling, navigation, and global scripts; there are no app-specific templates outside `templates/tools/pdf_merger.html`.
- External dependency: `pypdf` (see `requirements.txt`, currently `pypdf>=6.13.3`) supplies the PDF reader/writer functionality; keep merge views and inspect_pdf in sync with `pypdf`’s API.
- No other apps import `tools.views` or refer to `tools:` namespace in the repo, which implies the app is self-contained; no services or signals cross-link with other apps.

## 12. URL Surface / API Surface
- `path("", pdf_merger, name="index")`: renders the UI; GET-only.
- `path("merge/", merge_pdfs, name="merge_pdfs")`: POST-only merge endpoint expecting `files`.
- `path("delete-pages/", delete_pages, name="delete_pages")`: POST-only delete endpoint expecting `file` + `ranges`.
- `path("split/", split_pdf, name="split_pdf")`: POST-only split endpoint expecting `file` + `ranges`.

### Scan Inbox page (temporary internal tool)
- **`/tools/scan-inbox/`** (`tools:scan_inbox`) — three-column UI: pending PDF list, iframe preview, contract search + File/Skip. Access is **`@login_required` only** (no AppRegistry row; same as PDF Merger).
- JSON endpoints (all login-required; File/Skip are `@require_POST` + CSRF):
  - `tools:scan_inbox_items` — `list_pending()`
  - `tools:scan_inbox_pdf` — inline PDF preview (`xframe_options_sameorigin`, `%PDF` magic check)
  - `tools:scan_inbox_search` — `search_contracts(request.active_company, q)` (empty list if no active company)
  - `tools:scan_inbox_destination` — company-scoped contract + `resolve_destination`
  - `tools:scan_inbox_file` / `tools:scan_inbox_skip` — `file_pdf` / `skip_pdf`
- Template: `templates/tools/scan_inbox.html` (extends `base_template.html`, blocks `body` + `extra_scripts`).
- Front-end: `static/tools/js/scan_inbox.js` (vanilla JS, `textContent` only for server data). Styles under `/* === Scan Inbox === */` in `static/css/app-core.css`.
- Nav: sidebar link next to PDF Merger in `templates/base_template.html`.

## 13. Permissions / Security Considerations
- All views carry `@login_required`, so only authenticated users can access the tool, and the project likely relies on session-based auth from the `users` app.
- Merge/delete/split endpoints also use `@require_POST`; they reject GET requests outright.
- Server-side validation blocks non-PDF uploads, oversized files (per-file and combined), invalid ranges, and encrypted files that cannot be decrypted with an empty password; errors return HTTP 400 or 413 before any processing occurs.
- All client fetch calls attach CSRF tokens extracted from the `csrftoken` cookie; the view does not work without them.
- The app handles user-submitted binary files, so any change must keep the size/range constraints intact to avoid denial-of-service via oversized uploads.

## 14. Background Processing / Scheduled Work
- **`python manage.py scan_inbox_probe`** — Stage 0 diagnostic. Read-only by default; optional **`--test-write`** with **`--message-id`** exercises mail-folder create/move.
- **`python manage.py scan_inbox <subcommand>`** — Stage 1 backend CLI: `list`, `search`, `destination`, `file`, `skip`, `sweep`, `log`. Prints **full** Graph message IDs on `list`. `file` without **`--dry-run`** requires **`SCAN_INBOX_SHAREPOINT_WRITES=true`**.
- **Done rule:** a PDF is done when a `ScanFilingLog` row exists with the same `message_id` and `attachment_name` and `action` in (`FILED`, `SKIPPED`). `FAILED` does not mark done.
- **Destination ladder** (`scan_inbox_destination.resolve_destination`, read-only): confirmed contract drive ID → modern `files_url` → latest completed folder-scan snapshot (single in-scope row) → create path (IDIQ parent via Graph, else `Contract.get_sharepoint_relative_path()`). Never calls `resolve_contract_folder_path` or `contracts.services.drive_item_lookup`. Network errors → `kind=error`.
- **Never-overwrite:** SharePoint uploads use `@microsoft.graph.conflictBehavior=fail`; equal-size conflict treats existing file as already present; otherwise one retry with ` (2)` before `.pdf`.
- **Upload filename:** `Completed - {contract_number} - {YYYYMMDDHHMMSS}.pdf` where the stamp is `timezone.localtime(received_at)` from the message’s `receivedDateTime` (or `timezone.now()` if missing). Same stamp is exposed on queue items as `name_stamp` for the page preview. Bad SharePoint characters are still sanitized; conflict retry is still ` (2)` before `.pdf` (existing SharePoint files are not renamed).
- **Destination Graph lookups:** `scan_inbox_destination._sp_token()` caches `get_graph_access_token()` for 45 minutes; Graph GETs use a module-level `requests.Session()`. SharePoint writes use the same token helper via `_auth_headers()` and their own session.
- Settings: **`SCAN_INBOX_MAILBOX`**, **`SCAN_INBOX_ALLOWED_SENDERS`**, **`SCAN_INBOX_ALLOWED_SENDERS_LIST`**, **`SCAN_INBOX_SHAREPOINT_WRITES`**. Graph token via **`GRAPH_MAIL_*`**; drive via **`SHAREPOINT_DRIVE_ID`**.

## 15. Testing Coverage
- **`tools/tests/test_scan_inbox_probe.py`** — Stage 0 probe.
- **`tools/tests/test_scan_inbox_stage1.py`** — Stage 1 queue, destination, filing, sweep, search, CLI (HTTP mocked).
- PDF merge/split/delete views still have no automated tests.

## 16. Migrations / Schema Notes
- **`tools/migrations/0001_initial.py`** creates **`ScanFilingLog`** only.

## 17. Known Gaps / Ambiguities
- No automated tests exist, so you cannot rely on regression coverage when modifying parsing or upload logic.
- The app provides no navigation link in the repo; no other template references `tools:` so it is unclear how users reach `/tools/` outside manual discovery.
- The template’s inline script is the only place managing UI state; splitting the logic into static files may be desirable but requires careful coordination because the view expects the exact endpoint names and CSRF handling currently embedded in the template.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- When adjusting upload limits (`MAX_FILES`, `MAX_FILE_SIZE_BYTES`, `MAX_TOTAL_SIZE_BYTES`) keep the same values documented in both the view constants and the front-end script (which warns users at the same thresholds) so behavior stays consistent.
- Any change to `tools:merge_pdfs`, `tools:delete_pages`, or `tools:split_pdf` must be reflected in the inline JavaScript fetch URLs (`mergeUrl`, `deleteUrl`, `splitUrl`) and in `tools/urls.py`.
- Extend `_parse_page_ranges` with caution: both `delete_pages` and `split_pdf` rely on its exceptions to respond with `JsonResponse` errors; if you change its signature, update both callers and the template button enabling logic.
- Since no forms or serializers exist, adding new inputs requires updating the template, view validation, CSRF handling, and the front-end status messages simultaneously.
- There is no admin or persistent data, so refactors should focus on preserving the transient behavior (e.g., `PdfWriter` outputs, `ZipFile` naming conventions, response headers) when editing `views.py`.

## 19. Quick Reference
- Primary models: None (no Django models defined in `tools/models.py`).
- Main URLs: `/tools/` → `pdf_merger`, `/tools/merge/` → `merge_pdfs`, `/tools/delete-pages/` → `delete_pages`, `/tools/split/` → `split_pdf`.
- Key template: `templates/tools/pdf_merger.html` (single-page UI with inline JS).
- Key dependency: `pypdf` from `requirements.txt`.
- Risky files: `tools/views.py` (encapsulates all PDF handling logic) and `templates/tools/pdf_merger.html` (contains the JavaScript glue that triggers the views and enforces front-end state).


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
