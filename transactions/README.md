# Transactions App — Field Change History & In-Place Edit

The **transactions** app stores field-level changes for auditable models and provides a modal to **view history** and **edit** individual fields with change tracking. Only **changes** are recorded (not initial creation).

Use this README as the reference when adding transaction (edit + history) support to other pages or models.

---

## Table of Contents

1. [Model & storage](#model--storage)
2. [Recording changes (signals)](#recording-changes-signals)
3. [Request context (middleware)](#request-context-middleware)
4. [Field types & widgets](#field-types--widgets)
5. [Edit flow (backend)](#edit-flow-backend)
6. [Modal & frontend](#modal--frontend)
7. [How to add transactions to another page](#how-to-add-transactions-to-another-page)
8. [API reference](#api-reference)
9. [Project setup](#project-setup)

---

## Model & storage

### `Transaction` model

| Field         | Purpose                                      |
|---------------|----------------------------------------------|
| `content_type`| Django ContentType of the model that changed |
| `object_id`   | Primary key of the record                    |
| `field_name`  | Name of the field that changed               |
| `old_value`   | Serialized value before change (text)        |
| `new_value`   | Serialized value after change (text)         |
| `created_at`  | When the change occurred                     |
| `user`        | Who made the change (from request)           |

Indexes support listing by `(content_type, object_id)` and by `(content_type, object_id, field_name)` for per-field history.

---

## Recording changes (signals)

**File:** `transactions/signals.py`

- **TRACKED** is a list of `(model_class, field_name)` tuples. Only these model/field pairs are recorded.
- **pre_save** stores the current DB values for all TRACKED fields of the instance (by reading from the database before the save writes).
- **post_save** compares old vs new (from the instance) and creates a `Transaction` row for each changed TRACKED field.
- FK and date/datetime values are serialized (e.g. FK as pk string) so old/new compare correctly.

### Adding a new model or field

1. **Add to TRACKED:**

   ```python
   TRACKED = [
       (Contract, "contract_number"),
       (YourModel, "your_field"),
       # ...
   ]
   ```

2. **Add pre_save handling** in `store_old_state`:
   - For your model, add a branch that loads the current row with `.values("field1", "field2", "fk_id", ...)`.
   - Use `_serialize()` for values. For ForeignKey use the `_id` attribute name (e.g. `buyer_id`, `sales_class_id`) and store under the field name key (e.g. `"buyer"`).

Example (Contract):

```python
if sender is Contract:
    row = Contract.objects.filter(pk=instance.pk).values(
        "contract_number", "po_number", "buyer_id", ...
    ).first()
    if row is not None:
        old_state[key] = {
            "contract_number": _serialize(row.get("contract_number")),
            "buyer": _serialize(row.get("buyer_id")),
            # ...
        }
```

---

## Request context (middleware)

**File:** `transactions/middleware.py`

- **TransactionUserMiddleware** sets the current request user in a context variable so `post_save` can attach `user` to new `Transaction` rows.
- It also calls `clear_old_state()` after each request so the pre_save cache does not leak between requests.

**Required:** Add `TransactionUserMiddleware` to `MIDDLEWARE` in settings (see [Project setup](#project-setup)).

---

## Field types & widgets

**File:** `transactions/field_types.py`

- **get_field_info(content_type_id, field_name)** returns `{ "widget_type", "choices", "label" }` so the edit form can render the correct input.
- **Widget behavior:**
  - **DateField / DateTimeField** → `WIDGET_DATE` (calendar `type="date"`). Datetime fields default to date-only unless you add explicit datetime support later.
  - **IntegerField, FloatField, DecimalField** → number input.
  - **BooleanField** → select (Yes/No).
  - **ForeignKey** → select; choices from `_fk_choices()` (uses `name` or `description` or `str(obj)` for label).
  - **Field with choices** → select.
  - **Else** → text/textarea.

---

## Edit flow (backend)

**Files:** `views.py`, `forms.py`, `utils.py`, `urls.py`

- **GET** `/transactions/edit/<content_type_id>/<object_id>/<field_name>/`  
  Returns an HTML partial with: table name, field label, current value (read-only), new value input (correct widget), Save/Cancel, and change history table.
- **POST** same URL with form data (`new_value`, `csrfmiddlewaretoken`):
  - Validates with `EditFieldForm`.
  - Uses `utils.set_field_value(instance, field_name, raw_value)` then `instance.save(update_fields=[field_name])`.
  - The **signal** (post_save) creates the `Transaction` row; the view does not create it.
  - Returns JSON: `{ "success": true, "field_name", "content_type_id", "object_id", "display_value" }`.

**utils.py:**

- **get_field_value_display(instance, field_name)** — for form initial (e.g. date as `YYYY-MM-DD`).
- **set_field_value(instance, field_name, raw_value)** — coerces POST string to correct type (date, int, FK, decimal, etc.).
- **get_display_value(instance, field_name)** — for `display_value` in JSON response (e.g. formatted date, FK __str__).

---

## Modal & frontend

**File:** `templates/transactions/transaction_modal.html`

### Include the modal

In any template (e.g. base or a detail page):

```html
{% include "transactions/transaction_modal.html" %}
```

### Opening the edit modal

```javascript
openTransactionsEditModal(contentTypeId, objectId, fieldName);
```

- Loads the edit partial via GET, injects it into `#transactionsModalBody`.
- **Important:** Scripts inside the injected HTML do **not** run. The modal script therefore sets `form.action = editUrl` and attaches the submit handler **after** `body.innerHTML = html`. Do not rely on inline scripts in the edit partial for form submission.
- Submit: POST with `FormData` and `X-CSRFToken` header to the same edit URL; on success calls `window.onTransactionSaved(data)` and `closeTransactionsModal()`.

### Updating the page after save

Define a global callback (e.g. on the page that includes the modal):

```javascript
window.onTransactionSaved = function(data) {
  if (!data || !data.success) return;
  var fn = data.field_name;
  var displayVal = data.display_value || '';
  // Update a specific element, e.g. for a contract:
  if (data.content_type_id === window.contractContentTypeId && data.object_id === window.contractId) {
    var el = document.getElementById('contract-' + fn.replace(/_/g, '-') + '-value');
    if (el) el.textContent = displayVal || 'N/A';
  }
  // Or refetch a section (e.g. CLIN details):
  if (data.content_type_id === window.clinContentTypeId && clinId)
    fetchClinDetails(clinId);
};
```

### Optional: view-only history list

```javascript
openTransactionsModal(contentTypeId, objectId);
```

Shows all transactions for that object in the modal (no edit form).

---

## How to add transactions to another page

Follow these steps to add “click label to edit + history” to a new page or model.

### 1. Backend: track the fields

- In **`transactions/signals.py`**:
  - Append `(YourModel, "field_name")` to **TRACKED** for each field you want to record.
  - In **store_old_state** (pre_save), add a branch for `sender is YourModel` that:
    - Queries `YourModel.objects.filter(pk=instance.pk).values("field1", "fk_id", ...).first()`.
    - Builds a dict keyed by field name, with `_serialize(value)` for each value (use `_id` for FKs, key by field name).
    - Sets `old_state[key] = that_dict`.

If the model is in another app, import it in `signals.py` and add it to TRACKED/pre_save; no need to change the transactions app structure.

### 2. Include the modal and set IDs

In the page template:

```html
{% include "transactions/transaction_modal.html" %}
```

In the view, pass ContentType ids and object id(s) for the entity (and any sub-entity like CLIN):

```python
from django.contrib.contenttypes.models import ContentType
context['contract_content_type_id'] = ContentType.objects.get_for_model(Contract).id
context['clin_content_type_id'] = ContentType.objects.get_for_model(Clin).id
context['contract_id'] = contract.id  # or from URL
```

In the template or a script block, expose them for JS:

```html
<script>
  window.contractContentTypeId = {{ contract_content_type_id }};
  window.contractId = {{ contract.id }};
  window.clinContentTypeId = {{ clin_content_type_id }};
</script>
```

### 3. Make field labels open the edit modal

Use a **button** (or link with `role="button"`) that looks like text and calls the edit modal:

```html
<button type="button"
  onclick="openTransactionsEditModal({{ content_type_id }}, {{ object_id }}, 'field_name')"
  class="inline-block bg-transparent border-none shadow-none p-0 font-inherit text-gray-600 dark:text-gray-400 cursor-pointer hover:text-blue-600 dark:hover:text-blue-400 hover:underline focus:outline-none text-left appearance-none">
  Field Label
</button>
```

- **field_name** must match the model field name and one of the TRACKED entries.
- Use the same class string so labels look like plain text and only show underline/blue on hover.

### 4. Give each value element a stable id

So `onTransactionSaved` can update the DOM:

- Id pattern: **`{context}-{field_name_with_hyphens}-value`**.
- Example for “contract” context: `contract-contract-number-value`, `contract-po-number-value`, `contract-buyer-value` (field_name `contract_number`, `po_number`, `buyer` → underscores become hyphens).

```html
<p id="contract-contract-number-value" class="font-medium text-sm">{{ contract.contract_number|default:"N/A" }}</p>
```

### 5. Implement `onTransactionSaved`

- If you use the id pattern above, you can update by id:  
  `document.getElementById('contract-' + data.field_name.replace(/_/g, '-') + '-value').textContent = data.display_value;`
- If the section is dynamic (e.g. CLIN details loaded via AJAX), refetch that section when `data.content_type_id` and `data.object_id` match the current entity.

### 6. Optional: dynamic panels (e.g. CLIN details)

If part of the page is built in JS (e.g. `fetchClinDetails`), use the same pattern there:

- Each label: `<button type="button" onclick="openTransactionsEditModalForClin('field_name')" class="...">Label</button>`.
- `openTransactionsEditModalForClin` should resolve the current object id (e.g. selected CLIN) and call `openTransactionsEditModal(window.clinContentTypeId, clinId, fieldName)`.
- After save, call the same fetch (e.g. `fetchClinDetails(clinId)`) so the panel refreshes with the new value.

---

## API reference

| Method | URL | Purpose |
|--------|-----|--------|
| GET | `/transactions/list/<content_type_id>/<object_id>/` | HTML partial: table of all transactions for that object. |
| GET | `/transactions/edit/<content_type_id>/<object_id>/<field_name>/` | HTML partial: edit form (current value, new value input, history table). |
| POST | `/transactions/edit/<content_type_id>/<object_id>/<field_name>/` | Body: `new_value`, `csrfmiddlewaretoken`. Returns JSON `{ success, field_name, content_type_id, object_id, display_value }`. |
| GET | `/transactions/<pk>/` | HTML partial: one transaction detail (view-only, typed old/new). |
| GET | `/transactions/api/field-info/?content_type_id=&field_name=` | JSON: `{ widget_type, choices, label }` for building forms. |

All edit/list views require login. The project includes these under `path("transactions/", include("transactions.urls"))`.

---

## Project setup

1. **INSTALLED_APPS:** Include `"transactions.apps.TransactionsConfig"`.
2. **MIDDLEWARE:** Add `"transactions.middleware.TransactionUserMiddleware"` (after AuthenticationMiddleware so `request.user` is set).
3. **URLs:** In the root `urls.py`, add `path("transactions/", include("transactions.urls"))`.

After that, include the modal in templates and use `openTransactionsEditModal` / `onTransactionSaved` as above. For new models/fields, update **TRACKED** and **store_old_state** in `transactions/signals.py` as in [Recording changes](#recording-changes-signals) and [How to add transactions](#how-to-add-transactions-to-another-page).
