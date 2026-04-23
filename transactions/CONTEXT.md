# Transactions Context

## 1. Purpose
Track field-level edits for a handful of auditable models and surface that history in the UI while also letting staff overwrite a single field without leaving the page. The `transactions` app records every change to fields listed in `signals.TRACKED` (Contracts, CLINs, `ClinShipment.pod_date`, and Supplier detail fields) and exposes an AJAX-powered modal plus edit flow that reads from `Transaction` rows, shows typed values, and lets the user submit a new value that reuses the same history recording logic.

## 2. App Identity
- **Django app name:** `transactions`
- **AppConfig:** `TransactionsConfig` (`transactions/apps.py` defines `name = "transactions"`, `verbose_name = "Field change transactions"`, and imports `transactions.signals` in `ready()`).
- **Filesystem path:** `transactions/`
- **Role:** Support and audit app that provides a reusable change-history store and modal wiring for staff-facing data correction, not a standalone customer feature.

## 3. High-Level Responsibilities
- Persist every field change listed in `signals.TRACKED` as a `Transaction` row keyed by `ContentType` plus `object_id`, so history can be browsed by record or field (`models.py`, `signals.py`).
- Offer an AJAX list/detail/edit UI over `/transactions/.../` that renders `transactions/transaction_modal.html` plus partials, supporting view-only history and inline editing (`views.py`, `templates/transactions`).
- Determine form widget types and select choices for each tracked field via `get_field_info()`, so the edit modal renders date pickers, selects, numbers, or text areas (`field_types.py`, `forms.py`).
- Hold request-scoped metadata (current user plus cached old state) so signals attach `user` and compare deltas safely (`middleware.py`, `signals.py`).
- Surface change history in the admin as read-only rows for auditing (`admin.py`).

## 4. Key Files and What They Do
- `models.py`: Declares the single `Transaction` model (fields: `content_type`, `object_id`, `field_name`, `old_value`, `new_value`, `created_at`, `user`) with `Meta.indexes` tuned for per-record and per-field lookups.
- `forms.py`: Exposes `TransactionForm` (modal detail view that binds widgets using metadata) and `EditFieldForm` (single `new_value` entry that drives edits); both call `field_types.get_field_info` during `__init__`.
- `views.py`: Hosts `transaction_list`, `transaction_detail`, `field_info_api`, and `transaction_edit_field` (GET for partials and history, POST to coerce or overwrite a field). Each view is `@login_required` and the edit view returns JSON for the modal.
- `urls.py`: Namespaced `transactions` routes under `/transactions/...` for list, detail, edit, and field-info endpoints.
- `field_types.py`: Computes widget type (`WIDGET_*` constants) plus optional choices (booleans, ForeignKeys, fields with `choices`), limiting FK choice lists to 500 rows for performance.
- `utils.py`: Provides `get_field_value_display`, `set_field_value` (coercion for dates, FKs, numbers, booleans), and `get_display_value` for rendering updated values.
- `signals.py`: Defines `TRACKED` `(model_class, field_name)` tuples for `Contract`, `Clin`, `ClinShipment` (currently `pod_date`), and `Supplier`; stores pre-save state via `contextvars` and creates `Transaction` rows post-save when the serialized old value differs from the new.
- `middleware.py`: `TransactionUserMiddleware` writes the authenticated user to a contextvar, clears the `old_state` cache each request, and is wired into `MIDDLEWARE` after authentication (`STATZWeb/settings.py:86/98`).
- `admin.py`: Registers `Transaction` with read-only fields, filters, search, and `date_hierarchy` to support audits.
- `templates/transactions/transaction_modal.html` plus `templates/transactions/partials/*`: Provide the modal shell, history table, edit form, detail view HTML, and embedded scripts that manage the modal lifecycle.
- `README.md`: Step-by-step instructions for wiring the modal (`openTransactionsModal`, `openTransactionsEditModal`), tracking new fields, and understanding the API.

## 5. Data Model / Domain Objects
- **`Transaction`**: Stores one row per field delta, timestamped and optionally tied to a user (`related_name="field_transactions"`). `__str__` formats as `model#pk.field @ timestamp`, and `table_name` returns `content_type.model`.
- Uses `ContentType`/`object_id`/`GenericForeignKey`, so the record can belong to any app (contracts, suppliers, etc.).
- Indexed on `(content_type, object_id)` and `(content_type, object_id, field_name)` for listing history by record or field (`models.py`).
- No other models exist in this app.

## 6. Request / User Flow
1. Include `{% include "transactions/transaction_modal.html" %}` on any template that should expose history/editing (`README.md`). The modal’s script defines `openTransactionsModal`, `openTransactionsEditModal`, `showTransactionDetail`, and `closeTransactionsModal`, all of which issue `fetch` calls to this app’s URLs.
2. `GET /transactions/list/<content_type_id>/<object_id>/` (`transaction_list`) renders `transactions/partials/transaction_list.html`; rows call `showTransactionDetail(pk)` to load a detail partial.
3. `GET /transactions/<pk>/` (`transaction_detail`) renders `transaction_detail.html`, using `TransactionForm` so the stored `field_name`, `old_value`, and `new_value` appear with the proper widgets.
4. `GET /transactions/edit/<content_type_id>/<object_id>/<field_name>/` (`transaction_edit_field`) verifies the model/field exists, reads `get_field_value_display`, prepares `EditFieldForm`, and returns `transaction_edit.html` with the latest 20 transactions for that field.
5. `POST` to the same edit URL validates `EditFieldForm`, uses `utils.set_field_value` to coerce the raw string, saves the instance with `update_fields=[field_name]`, and returns JSON `{success, field_name, content_type_id, object_id, display_value}` so the caller can update the page without a full refresh.
6. `GET /transactions/api/field-info/?content_type_id=...&field_name=...` (`field_info_api`) returns the widget type, choices, and label so page scripts know what input to render before opening the edit modal.
All views are decorated with `@login_required`, and `transaction_edit_field` uses `JsonResponse` to surface validation errors or unknown fields.

## 7. Templates and UI Surface Area
- `transactions/transaction_modal.html` defines the overlay, header, loading message, and inline script that fetches partials, wires the edit form submission, and exposes the modal helpers as globals so any caller can call `openTransactionsEditModal(...)` or respond to `window.onTransactionSaved` (`templates/transactions/transaction_modal.html`).
- Partial templates under `templates/transactions/partials/`:
  - `transaction_list.html`: Tabular history with `humanize` formatting, clickable rows, and truncated old/new values.
  - `transaction_detail.html`: Metadata plus the `TransactionForm` fields (read-only) for a single change.
  - `transaction_edit.html`: Table and field labels, current value, the `EditFieldForm`, Save/Cancel buttons, a 20-row history table, and an embedded script that submits the form via `fetch` and triggers `window.onTransactionSaved`.
- UI is server-rendered partials injected via JavaScript; no heavy SPA framework is present, just vanilla `fetch` and DOM updates with Bootstrap-style classes.

## 8. Admin / Staff Functionality
`transactions/admin.py` registers `Transaction` with list display columns for the model/field/user/timestamp, filters on `content_type` and `created_at`, readonly fields for historical data, search over field names and values, and `date_hierarchy = "created_at"` so staff can browse the audit trail by time.

## 9. Forms, Validation, and Input Handling
- `TransactionForm` renders the stored `field_name`, `old_value`, and `new_value`. In `__init__`, it calls `get_field_info` to determine the widgets (date input, datetime, select, textarea, etc.) and applies `_input_attrs(editable=False)` for styling (`forms.py`).
- `EditFieldForm` exposes one `new_value` field. Its `__init__` fetches metadata from `get_field_info` to choose the correct widget and can preload `initial_value` so the modal shows the current value.
- Both forms expose a `field_info` property so callers can reuse widget metadata.
- `field_types.get_field_info` inspects the concrete field type, supplies `(value,label)` choices for booleans, ForeignKeys (using `_fk_choices` limited to 500 rows), and fields with `choices`, and returns the verbose name for UI labels.

## 10. Business Logic and Services
- `signals.py` contains the core logic: `TRACKED` enumerates the fields audited on `Contract` (contract_number, po_number, tab_num, buyer, due_date, award_date, sales_class, solicitation_type), `Clin` (item_type, clin_po_num, supplier, nsn, ia, fob, special_payment_terms, supplier_due_date, due_date, order_qty, ship_qty, ship_date, item_value, uom), `ClinShipment` (`pod_date`), and `Supplier` (cage_code, dodaac, allows_gsi, probation, conditional, archived, iso, ppi, special_terms, supplier_type, business_phone, primary_phone, business_email, primary_email, website_url).
- `store_old_state` (pre_save) queries the database for tracked values before the change, serializes them via `_serialize` (handling dates, datetimes, and FKs), and caches them in a request-scoped dictionary keyed by `(model_class, pk)`.
- `record_transactions` (post_save) compares serialized old values to the instance’s new values and creates `Transaction` rows only when the value changed; `get_current_user()` provides the user for attribution.
- `utils.set_field_value` handles coercion: it trims strings, enforces nullability, parses ISO dates/datetimes, resolves ForeignKeys by PK, converts numeric/decimal inputs, and normalizes booleans; it returns `False` when the conversion fails so the edit view can reject the request.
- `utils.get_field_value_display` returns `YYYY-MM-DD` strings for date pickers; `get_display_value` formats values for the page (using `get_<field>_display` when available or falling back to `strftime`).
- `field_types`, `forms`, `utils`, and `views.transaction_edit_field` cooperate so edits are validated, coerced, saved, and trigger signal-driven `Transaction` creation without duplicate logic.

## 11. Integrations and Cross-App Dependencies
- `contracts` and `suppliers` are imported directly in `signals.py`; `contracts.models.Contract`, `contracts.models.Clin`, `contracts.models.ClinShipment` (`pod_date`), and `suppliers.models.Supplier` fields listed in `TRACKED` trigger transactions.
- `users` (via `get_user_model()` in `models.py`) supplies the `user` FK on `Transaction`, and the middleware saves `request.user` into a contextvar consumed by `signals` (`middleware.py`, `signals.py`).
- `contenttypes` lets each `Transaction` point at any model; `ContentType` lookups appear in `models.py`, `views.py`, and `field_types.py`.
- `STATZWeb/settings.py` lists `"transactions.apps.TransactionsConfig"` under `INSTALLED_APPS` and adds `"transactions.middleware.TransactionUserMiddleware"` (after authentication) to `MIDDLEWARE`, ensuring the middleware runs every request.
- The README explains how to include the modal and call `openTransactionsEditModal`/`openTransactionsModal` from other templates, but nothing else in the repo currently references those helpers.

## 12. URL Surface / API Surface
| Path | Purpose |
| --- | --- |
| `GET /transactions/list/<content_type_id>/<object_id>/` | `transaction_list` -> renders `transactions/partials/transaction_list.html` with all transactions for a record (ordered by `created_at DESC`). |
| `GET /transactions/<pk>/` | `transaction_detail` -> renders `transactions/partials/transaction_detail.html` showing one change and typed old/new fields. |
| `GET /transactions/edit/<content_type_id>/<object_id>/<field_name>/` | `transaction_edit_field` (GET) -> returns `transaction_edit.html` (table, field info, edit form, last 20 field transactions). |
| `POST /transactions/edit/...` | `transaction_edit_field` (POST) -> validates `EditFieldForm`, coerces and saves the field, and returns JSON with `display_value` so the caller can refresh that field. |
| `GET /transactions/api/field-info/?content_type_id=...&field_name=...` | `field_info_api` -> JSON describing the widget type/choices/label for the field, or 400/404 on missing/unknown fields. |
All endpoints require authentication (`@login_required`).

## 13. Permissions / Security Considerations
- Views are decorated with `@login_required`, and the modal partials should only be included on pages shown to authorized staff.
- Edit requests run through `TransactionUserMiddleware`, which sets the authenticated user into a contextvar and calls `signals.clear_old_state()` after each request so state does not leak.
- `transaction_edit_field` returns JSON errors (`400` for invalid value, `404` for unknown model/field) and refuses to save unless `utils.set_field_value` and `form.is_valid()` succeed.
- Admin exposure is read-only—`TransactionAdmin.readonly_fields` prevents manual edits of historical data.
- The modal POST includes `X-CSRFToken`, `X-Requested-With`, and submits with `credentials: 'same-origin'` for security.

## 14. Background Processing / Scheduled Work
- No Celery/cron jobs; the only background work is Django signals: `pre_save` caches a tracked field’s previous value, `post_save` recomputes the delta, and a `Transaction` row is created when the values differ (`signals.py`).
- `TransactionUserMiddleware` keeps `_old_state_var` and `_current_user` clean by resetting them at the end of each request.

## 15. Testing Coverage
No `tests.py`, `tests/`, or other automated tests exist inside `transactions/`, so there is currently no coverage for the edit/history flow.

## 16. Migrations / Schema Notes
Only `migrations/0001_initial.py` exists (Django 4.2.24, Feb 12 2026). It creates the `Transaction` table with a `BigAutoField` primary key and the two indexes referenced in `models.py`. No later migrations are present.

## 17. Known Gaps / Ambiguities
- Despite the README showing how to call `openTransactionsEditModal`/`openTransactionsModal`, no other templates or JS currently import or call those helpers, so the modal is not wired to any real field.
- There are no automated tests for the signals, forms, or views, so regressions in `TRACKED` or `set_field_value` would go unnoticed.
- `transaction_edit_field` limits history to 20 rows per field, and extending `TRACKED` requires updating both the tuple list and `store_old_state` branches for that model.

## 18. Safe Modification Guidance for Future Developers / AI Agents
1. When adding new tracked fields, update `signals.TRACKED` and the `store_old_state` branch so the previous values for the new fields are cached and serialized.
2. Keep `TransactionUserMiddleware` in `MIDDLEWARE` and ensure it still calls `clear_old_state()` so `record_transactions` compares the right state.
3. When changing widget behavior, adjust `field_types.get_field_info`, `forms.TransactionForm/EditFieldForm`, and `templates/transactions/partials/transaction_edit.html` together because the modal injects HTML via `innerHTML` and binds its own JavaScript to the form.
4. Validate `utils.set_field_value` conversions for date/datetime, ForeignKey, numeric, decimal, and boolean fields—failed conversions result in a `400` and no `Transaction` record.
5. Preserve the modal helpers (`openTransactionsModal`, `openTransactionsEditModal`, `window.onTransactionSaved`) in `transaction_modal.html`, as they are the only entry points for pages that rely on this app.

## 19. Quick Reference
- **Primary model:** `transactions.models.Transaction` (generic, indexed on `content_type`, `object_id`, `field_name`).
- **Main URLs:** see `transactions/urls.py` for `list`, `detail`, `edit`, and `api/field-info` endpoints.
- **Key templates:** `templates/transactions/transaction_modal.html`, `transaction_list.html`, `transaction_detail.html`, `transaction_edit.html`.
- **Key dependencies:** `contracts.models.Contract`, `contracts.models.Clin`, `suppliers.models.Supplier`, `django.contrib.contenttypes`, `users` auth model, and `STATZWeb/settings.py` for installation/middleware.
- **Risky files:** `signals.py` (cross-app tracking), `middleware.py` (contextvar lifetimes), `field_types.py`/`forms.py`/`templates/partials/transaction_edit.html` (widget consistency), and `utils.py` (coercion success).


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
