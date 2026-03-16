# AGENTS.md — accesslog

## 1. Purpose of This File
This file defines safe-edit guidance for the `accesslog` Django app. It is written for AI coding agents and future developers making changes to this app.

Read `accesslog/CONTEXT.md` first if present — it describes the domain model, flows, and high-level responsibilities. This file focuses on execution safety, edit patterns, and known failure modes.

---

## 2. App Scope
`accesslog` is a **support/operations app**. It owns:
- Visitor check-in and check-out workflows
- Staged visitor queue (pre-check-in holding area)
- Monthly PDF report generation
- AJAX JSON endpoints for form auto-fill

It does **not** own:
- Authentication or authorization logic (delegated to `STATZWeb.decorators.conditional_login_required`)
- Any CRM, transaction, or inventory data
- Any shared models consumed by other apps — `Visitor` and `Staged` are not imported anywhere else in the project

This app is **isolated** at the model layer. Its only outbound dependency is the shared decorator.

---

## 3. Read This Before Editing

### Before changing models (`models.py`)
- Read `forms.py` — `VisitorCheckInForm` is a `ModelForm` bound to `Visitor` and explicitly lists fields
- Read `views.py` — `generate_report` accesses fields directly by attribute name (e.g., `visitor.date_of_visit`, `visitor.time_in`, `visitor.time_out`, `visitor.visitor_name`, `visitor.visitor_company`, `visitor.reason_for_visit`)
- Read `check_in.html` — JavaScript uses hardcoded DOM IDs derived from field names: `id_visitor_name`, `id_visitor_company`, `id_reason_for_visit`, `id_is_us_citizen`
- Check the migrations directory for existing schema history before altering field types or nullability

### Before changing views (`views.py`)
- Read `urls.py` — confirm URL names and parameter types (`visitor_id` is `int`, `staged_id` is `int`)
- Read the relevant template — context keys must match what templates expect
- Note: `check_out_visitor` uses `Visitor.objects.get(id=visitor_id)` (no `try/except`, no `get_object_or_404`) — this raises a 500 on invalid IDs

### Before changing forms (`forms.py`)
- Read `check_in.html` — `VisitorHistoryField` choice values are consumed directly by inline JavaScript
- The staged visitor detection in JS relies on choice values being numeric strings for staged entries and `"Name - Company"` format strings for history entries — any change to these formats breaks the JS logic

### Before changing templates
- Read the inline `<script>` block in `check_in.html` — it parses dropdown values with hardcoded assumptions and uses hardcoded element IDs
- `visitor_log.html` renders `MonthYearForm` via Crispy Forms — changing the form field name `month_year` requires updating the POST handler in `generate_report`

### Before changing report generation (`generate_report` in `views.py`)
- The PDF uses hardcoded `x_positions = [50, 130, 230, 330, 430, 480]` mapped positionally to `['Date', 'Name', 'Company', 'Reason', 'Time In', 'Time Out']`
- Column order and field names are tightly coupled — adding or reordering columns requires updating both the headers list and the data list together
- `reportlab` must remain in `requirements.txt`

---

## 4. Local Architecture / Change Patterns
- All business logic lives directly in `views.py`. There are no service modules, managers, or signal handlers.
- Validation is handled by `VisitorCheckInForm` (a `ModelForm`). There are no custom `clean` methods — validation is Django's built-in field validation only.
- Templates contain **non-trivial inline JavaScript** (`check_in.html`). This is not thin presentation logic — treat the script block as tightly coupled to the form and JSON endpoints.
- Admin uses bare `admin.site.register` with no customization. It is not a primary UI surface.
- The app follows a direct, procedural style. There is no service layer to introduce unless refactoring intentionally.

---

## 5. Files That Commonly Need to Change Together

### Adding or renaming a `Visitor` field
`models.py` → `forms.py` (Meta fields list + widget/label dicts) → `views.py` (PDF data array, JSON response dict) → `check_in.html` (DOM IDs, JS field references) → new migration

### Adding or renaming a `Staged` field
`models.py` → `forms.py` (`VisitorHistoryField.populate_choices` if display changes) → `views.py` (`check_in_visitor` staging block, `get_staged_info` JSON response) → `check_in.html` (JS `fillVisitorInfo` that maps JSON keys to DOM fields) → new migration

### Adding a new URL
`urls.py` → `views.py` (new view function) → template (link/form action) → update any `{% url %}` references

### Changing `VisitorHistoryField` choice format
`forms.py` (`populate_choices` value format) → `check_in.html` inline JS (`fillVisitorInfo`: the `isNaN` check distinguishes staged vs history by numeric vs string value)

---

## 6. Cross-App Dependency Warnings

### This app depends on
- `STATZWeb.decorators.conditional_login_required` — applied to every view. If its redirect target, group requirements, or behavior changes, all `accesslog` views are affected. Inspect `STATZWeb/decorators.py` before modifying auth behavior.
- `base_template.html` (shared) — both templates extend it. Block names `body` and `extra_scripts` must remain valid.
- `reportlab` third-party package — required for `generate_report`. Keep in `requirements.txt`.

### No apps depend on this app
Confirmed by repo-wide grep: no other app imports `Visitor`, `Staged`, or any `accesslog` module. The app is isolated at the model layer.

### URL namespace
The app uses `app_name = 'accesslog'`. The `{% url 'accesslog:visitor_log' %}` and `{% url 'accesslog:check_in' %}` references exist inside the app's own templates only. The project `STATZWeb/urls.py` mounts the app at `path('accesslog/', include('accesslog.urls'))`.

---

## 7. Security / Permissions Rules
- Every view is decorated with `@conditional_login_required`. **Do not remove or bypass this decorator** on any existing or new view, including the AJAX JSON endpoints (`get_visitor_info`, `get_staged_info`).
- There are no object-level permissions. Any authenticated user can check in, check out, stage, or export PDFs.
- The PDF export streams sensitive visitor data (names, companies, citizenship flags). Do not add caching, public URLs, or unauthenticated access to the `generate_report` route.
- `check_out_visitor` uses `Visitor.objects.get(id=visitor_id)` — this will raise a 500 on an invalid ID. If refactoring, replace with `get_object_or_404`.
- `generate_report` parses `month_year` with `split('-')` after form validation. Trust the form to constrain input; do not bypass `form.is_valid()` in this view.

---

## 8. Model and Schema Change Rules
- **Before renaming any field on `Visitor`**: search `views.py` for direct attribute access, update the PDF data list in `generate_report`, update `get_visitor_info` JSON keys, update the `VisitorCheckInForm` Meta and widget/label dicts, update DOM IDs and JS field mappings in `check_in.html`, create a migration.
- **Before renaming any field on `Staged`**: update `get_staged_info` JSON keys, update `check_in_visitor` staging block, update `VisitorHistoryField.populate_choices`, update JS `fillVisitorInfo` in `check_in.html`, create a migration.
- **`time_out` is nullable** (`null=True, blank=True`). The PDF rendering handles this with `if visitor.time_out else ''`. Any code touching `time_out` must preserve the null case.
- **`date_of_visit` defaults to `timezone.now`** (date). `time_in` defaults to `timezone.now` (datetime). In `check_in_visitor`, both are explicitly overwritten at save time — do not rely on the model default for these fields in the check-in flow.
- Do not merge `Staged` into `Visitor` without updating the JS distinction logic and the `staged_id` hidden input flow.

---

## 9. View / URL / Template Change Rules
- URL names (`visitor_log`, `check_in`, `check_out`, `generate_report`, `visitor_info`, `staged_info`) are used via `{% url %}` tags inside this app's own templates and via `redirect('accesslog:...')` in views. Search both when renaming.
- `check_in.html` uses **hardcoded absolute fetch paths** (`/accesslog/staged-info/` and `/accesslog/visitor-info/`). If the mount path in `STATZWeb/urls.py` changes, these JS fetch calls will silently break. Consider using `{% url %}` in a `<script>` variable to make these maintainable.
- The `visitor_history` dropdown in `check_in.html` is rendered manually (not via `{{ form.visitor_history }}`), iterating `form.visitor_history.field.choices` directly. If the field is renamed or its `choices` API changes, update the template loop.
- `MonthYearForm` is instantiated without POST data in `visitor_log` (display only) and with POST data in `generate_report`. Keep both call sites in sync if the form changes.
- The PDF page footer hard-codes `"Page 1"` — multi-page PDFs do not update this. This is a known cosmetic issue; don't fix it incidentally during other edits.

---

## 10. Forms / Serializers / Input Validation Rules
- `VisitorCheckInForm` validates using Django's built-in ModelForm validation. There are no custom `clean` methods. Do not add validation logic to the JavaScript — keep it server-side.
- `VisitorHistoryField.populate_choices()` is called explicitly in `check_in_visitor` (GET path) and in `VisitorCheckInForm.__init__`. The GET path calls `populate_choices()` again after instantiation: `form.fields['visitor_history'].populate_choices()`. This means choices are populated **twice** on GET — once in `__init__` and once in the view. This is redundant but harmless; do not remove either call without verifying both paths still work.
- `MonthYearForm` choices are populated at `__init__` time by querying `Visitor`. If no visitor records exist, the dropdown will only contain the placeholder, and `generate_report` will redirect without user feedback.
- Field names in `forms.py` Meta must match what the templates reference by `name` attribute and what views access via `form.cleaned_data`.

---

## 11. Background Tasks / Signals / Automation Rules
There are **no signals, Celery tasks, scheduled jobs, or management commands** in this app. All processing is synchronous and request-scoped.

The only notable async-adjacent behavior is:
- The inline JavaScript in `check_in.html` makes two `fetch()` calls to AJAX endpoints. These are client-side only and require the `get_visitor_info` and `get_staged_info` endpoints to remain live and authenticated.

---

## 12. Testing and Verification Expectations
`tests.py` contains only the default comment placeholder — **there are no automated tests**.

After any edit, manually verify these flows:

| Flow | Key Check |
|---|---|
| Visit `GET /accesslog/` | Visitor table renders; MonthYearForm present |
| `GET /accesslog/check-in/` | Dropdown populates with staged + previous visitors |
| Select a staged visitor from dropdown | Form fields auto-fill via fetch; `staged_id` hidden input set |
| Select a previous visitor from dropdown | Form fields auto-fill via fetch; `staged_id` remains `0` |
| Submit check-in (Check In button) | Visitor created; staged record deleted if applicable; redirect to log |
| Submit check-in (Stage Visitor button) | Staged record created; redirect to log |
| POST `/accesslog/check-out/<id>/` | Visitor `time_out` set; `departed=True`; redirect to log |
| POST `/accesslog/generate-report/` | PDF downloads with correct month data |
| Admin `/admin/accesslog/` | Visitor and Staged lists render without error |

If `reportlab` is missing or outdated, `generate_report` will raise an import error at request time.

---

## 13. Known Footguns

1. **`check_out_visitor` has no 404 guard** — `Visitor.objects.get(id=visitor_id)` raises `Visitor.DoesNotExist` (500) on bad IDs. This is not currently a user-visible risk since check-out buttons are rendered per-record, but it becomes one if the URL is called externally.

2. **Hardcoded fetch paths in JS** — `/accesslog/staged-info/` and `/accesslog/visitor-info/` in `check_in.html` are not Django `{% url %}` tags. A mount point change in `STATZWeb/urls.py` silently breaks auto-fill with no server-side error.

3. **Staged vs. history distinction is numeric string detection** — JS uses `isNaN(select.value)` to distinguish staged (numeric ID) from history (name string). Any choice value that looks like a number but is not a staged ID will be treated as staged and trigger a fetch to `staged-info/`. Separator options use `value=""` to avoid this, but this is fragile if `VisitorHistoryField` is refactored.

4. **PDF column layout is positional** — `x_positions` in `generate_report` is a plain list of integers mapped by index to field data. Adding a column in the middle breaks alignment for all subsequent columns silently.

5. **`MonthYearForm` gives no feedback on empty submission** — `generate_report` redirects to `visitor_log` without a user-visible error if the form is invalid or no month is selected.

6. **`visitor_history` choices populated twice on GET** — `VisitorCheckInForm.__init__` calls `populate_choices()` and so does the GET branch in `check_in_visitor`. Redundant DB queries on every form load.

7. **`console.log` debug statements remain in production code** — `check_in.html` and `views.py` both have `print()` / `console.log()` statements. These are not harmful but expose visitor names in server logs and browser consoles.

8. **URL name `visitor_log` is defined twice** — `urls.py` has both `path('', ..., name='visitor_log')` and `path('visitor_log/', ..., name='visitor_log')`. Django uses the last definition for `reverse()`. Both routes work, but only the second one is what `{% url 'accesslog:visitor_log' %}` will resolve to.

---

## 14. Safe Change Workflow

1. Read `CONTEXT.md` to understand the domain and flows.
2. Read the specific files involved (`models.py`, `views.py`, `forms.py`, template).
3. Search repo-wide for any references to the symbol being changed — though for this app, cross-app references are minimal.
4. Make the smallest scoped change needed.
5. Update all coupled files in the same cluster (see Section 5).
6. If adding or modifying a model field, create a migration.
7. Manually run through the affected flow in the browser (see Section 12 checklist).
8. Confirm `reportlab` is installed if touching `generate_report`.
9. Confirm `@conditional_login_required` is present on all views.

---

## 15. Quick Reference

| Category | Items |
|---|---|
| Primary files | `models.py`, `views.py`, `forms.py`, `templates/accesslog/check_in.html` |
| Main coupled areas | `VisitorHistoryField` choices ↔ JS `fillVisitorInfo`; `Visitor` fields ↔ PDF columns; `staged_id` hidden input ↔ `check_in_visitor` POST handler |
| Cross-app dependencies | `STATZWeb.decorators.conditional_login_required` (inbound); `base_template.html` (shared); `reportlab` (third-party) |
| Security-sensitive areas | Every view needs `@conditional_login_required`; PDF export streams PII |
| Riskiest edit types | Renaming `Visitor` fields (PDF + JS + form + template); changing `VisitorHistoryField` value format (JS detection logic); modifying `generate_report` column layout |
| No automated tests | Verify manually using the checklist in Section 12 |
