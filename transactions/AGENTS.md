# AGENTS.md — `transactions` app

Read `transactions/CONTEXT.md` first for domain overview. This file focuses on safe-edit mechanics and failure modes.

---

## 1. Purpose of This File

Defines how to modify the `transactions` app safely. This is an audit/support app: one wrong edit can silently break field-change recording across `contracts` and `suppliers` — with no tests to catch it.

---

## 2. App Scope

**Owns:**
- `Transaction` model (one row per field delta, generic via ContentType)
- Signal-driven capture of old/new values for tracked fields
- AJAX modal + partials for viewing history and inline editing
- `TransactionUserMiddleware` (contextvar lifecycle)
- Widget-type resolution (`field_types.py`) and coercion (`utils.py`)

**Does not own:**
- The models being tracked (`Contract`, `Clin`, `Supplier` belong to `contracts` and `suppliers`)
- The UI templates that call `openTransactionsEditModal` (those live in `templates/suppliers/supplier_detail.html` and `contracts/templates/contracts/contract_management.html`)
- Authentication or user management

This is a **glue/audit app** — thin in domain logic, but structurally fragile because its signal handlers are globally registered on all saves.

---

## 3. Read This Before Editing

### Before changing tracked fields
- `transactions/signals.py` — `TRACKED` list and both signal receivers (`store_old_state`, `record_transactions`)
- The `.values(...)` calls inside each model branch of `store_old_state` are **hardcoded separately from `TRACKED`** — they must be kept in sync
- `contracts/models.py`, `suppliers/models.py` — confirm field names and types match what signals expect

### Before changing widget/form behavior
- `transactions/field_types.py` — `get_field_info()` and `_fk_choices()`
- `transactions/forms.py` — `TransactionForm._set_value_widgets()` and `EditFieldForm._set_widget()`
- `transactions/templates/transactions/partials/transaction_edit.html` — the edit partial is injected via `innerHTML`; its form field names and JS submit handler must stay aligned with `EditFieldForm`

### Before changing views or URLs
- `transactions/urls.py` — all four URL names: `transaction_list`, `transaction_detail`, `transaction_edit_field`, `field_info`
- `transactions/templates/transactions/transaction_modal.html` — hardcodes URL patterns using `fetch` calls; no Django `{% url %}` tags — path strings must match
- `templates/suppliers/supplier_detail.html` — calls `openTransactionsEditModal(supplier_content_type_id, supplier.id, 'field_name')` for ~15 fields
- `contracts/templates/contracts/contract_management.html` — calls `openTransactionsEditModal(contract_content_type_id, contract.id, 'field_name')` for Contract fields

### Before changing middleware
- `STATZWeb/settings.py:98` — `TransactionUserMiddleware` placement in `MIDDLEWARE` (must be after authentication middleware)
- `transactions/middleware.py` — contextvar lifecycle: user set on request entry, cleared in `finally` block along with `clear_old_state()`
- `transactions/signals.py` — `get_current_user()` and `clear_old_state()` are imported from middleware

### Before changing models or migrations
- `transactions/migrations/0001_initial.py` — only migration; two named indexes (`tx_content_object_idx`, `tx_field_history_idx`) must remain if referenced
- `transactions/admin.py` — `readonly_fields`, list display, and filters reference `Transaction` field names directly

---

## 4. Local Architecture / Change Patterns

- **No services layer.** Logic lives in `signals.py` (recording), `utils.py` (coercion), `field_types.py` (widget resolution), and `views.py` (orchestration). Keep new logic in the same file that owns the concern.
- **Views are thin orchestrators.** They call `get_field_info`, `get_field_value_display`, `set_field_value`, `get_display_value`, and delegate saving to the model instance. Keep views that way.
- **Signal receivers are globally registered** via `@receiver(pre_save)` / `@receiver(post_save)` with no `sender=` filter — they fire on every model save in the app and filter by sender class inside the handler. This is intentional but means any import of `transactions.signals` activates them.
- **Widget parity is essential.** `field_types.get_field_info` drives both the read-only `TransactionForm` and the editable `EditFieldForm`. A mismatch between widget type and `utils.set_field_value` coercion logic will cause silent bad saves or `400` errors.
- **Inline edit flow is tightly coupled across layers.** The POST path is: `transaction_modal.html` (JS fetch) → `views.transaction_edit_field` → `EditFieldForm.is_valid()` → `utils.set_field_value` → `instance.save(update_fields=[field_name])` → `pre_save` signal → `post_save` signal → `Transaction.objects.create(...)`. Every link matters.

---

## 5. Files That Commonly Need to Change Together

### Adding a new tracked field
1. `signals.py` — add `(ModelClass, "field_name")` to `TRACKED`
2. `signals.py` — add the field to the `.values(...)` call and the `old_state[key]` dict inside `store_old_state` for the correct model branch
3. Confirm `field_types.get_field_info` returns the correct widget type for that field (it introspects the model, so often no change needed unless it's an unusual field type)
4. Confirm `utils.set_field_value` handles that field's type correctly

### Adding a new tracked model
1. `signals.py` — add import, new `TRACKED` entries, and a new `elif sender is MyModel:` branch inside `store_old_state` with `.values(...)` + `old_state[key]` dict
2. The caller template — include `{% include "transactions/transaction_modal.html" %}` and call `openTransactionsEditModal(content_type_id, object_id, 'field_name')` from buttons
3. The caller view — pass `<model>_content_type_id` to the template context

### Changing widget type behavior
1. `field_types.py` — `get_field_info()` return dict
2. `forms.py` — `TransactionForm._set_value_widgets()` and `EditFieldForm._set_widget()`
3. `templates/transactions/partials/transaction_edit.html` — if HTML input structure changes, verify JS submit path in `transaction_modal.html` still reads `new_value` correctly

### Changing URL structure
1. `urls.py`
2. `transaction_modal.html` — JS fetch URL strings (not Django `{% url %}` — hardcoded path prefixes)
3. Root `urls.py` (wherever `transactions/` is included)

---

## 6. Cross-App Dependency Warnings

### This app depends on:
- `contracts.models.Contract` and `contracts.models.Clin` — imported directly in `signals.py`
- `suppliers.models.Supplier` — imported directly in `signals.py`
- `django.contrib.contenttypes` — `ContentType` used in model, views, and field_types
- `users` (via `get_user_model()`) — FK on `Transaction.user`
- `STATZWeb/settings.py` — for `INSTALLED_APPS` and `MIDDLEWARE` registration

### Apps that depend on this app:
- `suppliers` — `templates/suppliers/supplier_detail.html` includes `transaction_modal.html` and calls `openTransactionsEditModal` for ~15 `Supplier` fields; the view passes `supplier_content_type_id` as context
- `contracts` — `contracts/templates/contracts/contract_management.html` calls `openTransactionsEditModal` for `Contract` fields; the view passes `contract_content_type_id` as context

### Rename/removal risk:
- Renaming any field in `signals.TRACKED` by string (e.g. `"cage_code"`) requires updating: `TRACKED` tuple, `store_old_state` `.values()` call and dict key, and all `openTransactionsEditModal(...)` call sites in `supplier_detail.html` / `contract_management.html`
- Removing `TransactionUserMiddleware` from settings silently breaks user attribution on all future `Transaction` rows
- Removing `clear_old_state()` from the middleware `finally` block can cause state leakage between requests in the same thread/async context

---

## 7. Security / Permissions Rules

- All four views are decorated `@login_required`. Do not remove these.
- `transaction_edit_field` is the only write endpoint. It validates via `EditFieldForm.is_valid()` and `utils.set_field_value` before calling `.save()`. Both gates must pass.
- The POST body must include `X-CSRFToken` (sent by the modal JS). Do not remove or weaken the CSRF wiring in `transaction_modal.html`.
- `Transaction` records are historical audit data. `TransactionAdmin` has `readonly_fields` — do not convert those to editable without explicit intent.
- `_fk_choices` queries the database for FK option lists capped at 500 rows. Removing the cap risks slow page loads for large tables.
- The edit endpoint accepts arbitrary `field_name` via URL but validates it against `model._meta.get_field()` and `get_field_info()` before proceeding — this guard must be preserved.

---

## 8. Model and Schema Change Rules

- Only one model: `Transaction`. It is append-only by design — no update/delete in normal flows.
- `old_value` and `new_value` are `TextField(blank=True, null=True)`. All values are stored as strings (serialized by `_serialize()`). Do not add type constraints.
- The two named indexes (`tx_content_object_idx`, `tx_field_history_idx`) support the primary query patterns. Do not drop them without profiling.
- `object_id` is `PositiveIntegerField` — this breaks if any tracked model uses non-integer PKs.
- Renaming `field_name`, `old_value`, or `new_value` on `Transaction` requires updating `admin.py`, `forms.py` (`Meta.fields`), both templates (`transaction_detail.html`, `transaction_list.html`, `transaction_edit.html`), and any direct `.filter(field_name=...)` calls in `views.py`.
- Only one migration exists (`0001_initial`). New migrations are straightforward but must not alter the indexes without checking admin queries.

---

## 9. View / URL / Template Change Rules

- URL names are in the `transactions` namespace. The modal JavaScript does **not** use Django `{% url %}` — it builds paths from a hardcoded prefix. If the URL prefix changes in root `urls.py`, update the JS fetch paths in `transaction_modal.html` too.
- The four URL names are: `transactions:transaction_list`, `transactions:transaction_detail`, `transactions:transaction_edit_field`, `transactions:field_info`. Search for these strings if renaming.
- `transaction_modal.html` is a shared partial included by `supplier_detail.html` and `contract_management.html`. Changes to its API (function signatures, global names, callback contracts) break both callers.
- `window.onTransactionSaved` is the callback hook used by `supplier_detail.html` to refresh displayed values after a successful edit. Do not rename this without updating both caller templates.
- The partial templates (`transaction_list.html`, `transaction_detail.html`, `transaction_edit.html`) are injected into the modal via `innerHTML`. They must not rely on page-level scripts or styles that aren't available inside a modal overlay.
- Context variable names matter: `table_name`, `field_name`, `field_label`, `old_value_display`, `content_type_id`, `object_id` are all used in `transaction_edit.html`. Renaming any of these in `views.py` requires updating the template.

---

## 10. Forms / Serializers / Input Validation Rules

- `EditFieldForm` has a single `new_value = CharField(required=False)`. Widget is set dynamically in `__init__`. The form itself does minimal validation — the real coercion gate is `utils.set_field_value`.
- `utils.set_field_value` returns `False` on coercion failure. The view checks this and returns a `400`. Do not remove this check or call `.save()` if it returns `False`.
- Empty string handling in `set_field_value`: empty input sets `None` on nullable fields and rejects non-nullable fields. This is by design.
- `TransactionForm` is read-only (view-only modal). It does not validate on POST and should not be converted to an editable form.
- Widget-type constants (`WIDGET_TEXT`, `WIDGET_DATE`, etc.) are defined in `field_types.py` and imported in `forms.py`. Do not hardcode widget strings elsewhere.

---

## 11. Background Tasks / Signals / Automation Rules

- **No Celery, no cron jobs.** All recording is synchronous, triggered by Django's `pre_save` and `post_save` signals.
- `store_old_state` (`pre_save`) fires on **every model save in the application** — not just for tracked models. It early-returns quickly for non-tracked senders, but it still adds overhead. Avoid adding heavy logic here.
- `record_transactions` (`post_save`) pops the old state for the key `(sender, instance.pk)` from the contextvar dict. If the pre_save didn't run (e.g., bulk operations that bypass signals), `old` will be `None` and no `Transaction` is created. This is a known gap — bulk updates are not tracked.
- `TransactionUserMiddleware` clears both contextvars in a `finally` block. If you add middleware, preserve the ordering in `MIDDLEWARE` (must come after auth middleware).
- The signals module is imported via `TransactionsConfig.ready()` in `apps.py`. Do not move this import or the signals will not register.

---

## 12. Testing and Verification Expectations

There are **no automated tests** in this app. After any edit, verify manually:

1. **Signal recording** — Edit a tracked field on a `Contract`, `Clin`, or `Supplier` via the edit modal. Confirm a `Transaction` row appears in Django admin at `/admin/transactions/transaction/`.
2. **Edit modal flow** — Open `supplier_detail` or `contract_management`, click an editable field label. Confirm the modal loads with the correct current value and widget type (date picker for dates, dropdown for FK/choice fields, text for strings).
3. **POST and display update** — Submit a new value in the modal. Confirm: no page reload, the displayed value updates in-place, and the `Transaction` row shows correct `old_value`/`new_value`.
4. **User attribution** — Check the new `Transaction` row has the correct user.
5. **Field type coverage** — If you changed `field_types.py` or `utils.py`, test at least one field of each type: date, FK (e.g. `supplier` on Clin), boolean (e.g. `allows_gsi`), and text (e.g. `cage_code`).
6. **Middleware cleanup** — Confirm no state leaks: make two sequential edits and verify each `Transaction` has the correct `old_value` (not a stale value from the prior request).
7. **Admin** — Visit `/admin/transactions/transaction/` and verify list display, filters, and `date_hierarchy` still render.

---

## 13. Known Footguns

- **`TRACKED` and `store_old_state` are not in sync automatically.** Adding a tuple to `TRACKED` without also adding the field to the `.values()` call and `old_state[key]` dict means the field will never be recorded — silently.
- **`store_old_state` branches are hardcoded per model.** A new `TRACKED` model requires a new `elif sender is NewModel:` branch. There is no generic fallback.
- **Bulk saves bypass signals.** `QuerySet.update()` does not call `pre_save`/`post_save`. Any code path that uses `.update(field=value)` instead of `.save(update_fields=[...])` will silently skip transaction recording.
- **`instance.save(update_fields=[field_name])` in `views.py` triggers both signals.** `pre_save` will capture old state, and `post_save` will record the delta. If this save call is changed to `.update()` for any reason, recording breaks entirely.
- **The modal JS path strings are not tied to Django's URL reversing.** If the `transactions/` URL prefix changes in `STATZWeb/urls.py`, the modal's `fetch()` calls in `transaction_modal.html` will 404 silently.
- **`_fk_choices` uses `hasattr(related_model, "name")` to pick the label attribute.** This attribute check is against the class, not an instance — if a model has a `name` classmethod or property, it will be picked. Verify FK choice labels are sensible after adding a new FK-typed tracked field.
- **ContentType IDs are environment-specific.** The caller templates pass `supplier_content_type_id` and `contract_content_type_id` from the view context. If ContentType rows are ever manually deleted or re-seeded, these IDs change. Never hardcode numeric ContentType IDs.
- **`TransactionUserMiddleware` must stay in MIDDLEWARE after authentication.** Moving it before auth means `request.user` may not be set, and all `Transaction.user` values will be `None`.
- **No tests.** Regressions in signal field serialization, `set_field_value` coercion, or widget selection will not be caught automatically.

---

## 14. Safe Change Workflow

1. Read `transactions/CONTEXT.md` for domain overview.
2. Read the specific files involved in your change (signals, utils, field_types, forms, or views).
3. Search `templates/suppliers/supplier_detail.html` and `contracts/templates/contracts/contract_management.html` for any field names or modal function calls you're modifying.
4. If adding a tracked field: update both `TRACKED` and the `.values()` + dict in `store_old_state` for the correct model branch.
5. If changing widget types or coercion: verify `field_types.py`, `forms.py`, `utils.py`, and `partials/transaction_edit.html` are all consistent.
6. If changing URLs or modal JS API: update `urls.py`, `transaction_modal.html` fetch paths, and both caller templates.
7. Make minimal, scoped changes. The signal receivers touch every save globally — any logic change has wide blast radius.
8. Manually verify the full modal flow (open, view history, submit edit, check `Transaction` row in admin).
9. Confirm middleware cleanup still works (check that a second edit shows the correct prior value, not a stale one).

---

## 15. Quick Reference

| Area | Primary files |
|---|---|
| Field tracking logic | `signals.py` (`TRACKED`, `store_old_state`, `record_transactions`) |
| Widget resolution | `field_types.py` (`get_field_info`, `_fk_choices`) |
| Form/input | `forms.py` (`TransactionForm`, `EditFieldForm`) |
| Value coercion | `utils.py` (`set_field_value`, `get_field_value_display`, `get_display_value`) |
| Views | `views.py` (4 views, all `@login_required`) |
| URLs | `urls.py` (namespace `transactions`) |
| Modal shell + JS | `templates/transactions/transaction_modal.html` |
| Edit partial | `templates/transactions/partials/transaction_edit.html` |
| Middleware | `middleware.py` (`TransactionUserMiddleware`) |
| Admin | `admin.py` (read-only audit view) |

**Main coupled areas:** `TRACKED` ↔ `store_old_state` branches; `field_types` ↔ `forms` ↔ `utils` ↔ `transaction_edit.html`; modal JS ↔ URL paths ↔ caller templates.

**Main cross-app dependencies:** `contracts.models.Contract`, `contracts.models.Clin`, `suppliers.models.Supplier` (imported in signals); `templates/suppliers/supplier_detail.html` and `contracts/templates/contracts/contract_management.html` (call modal helpers).

**Security-sensitive:** `@login_required` on all views; CSRF token in modal POST; `set_field_value` return check before `.save()`; `TransactionAdmin.readonly_fields`.

**Riskiest edit types:** Adding new tracked fields (dual update required in signals), changing URL prefix (JS not Django-aware), bulk save refactors in contracts/suppliers (bypass signals silently), removing middleware `finally` cleanup (state leakage).
