# AGENTS.md — inventory
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

Read `inventory/CONTEXT.md` first. This file does not repeat that content; it defines safe-edit rules grounded in the actual code.

---

## 1. Purpose of This File

This file tells AI coding agents how to safely modify the `inventory` app. It identifies coupled files, real breakage risks, cross-app dependencies, and which patterns to follow when making changes.

---

## 2. App Scope

**Owns:** The warehouse stock ledger — `InventoryItem` rows stored in `STATZ_WAREHOUSE_INVENTORY_TBL`. All CRUD, autocomplete, and the computed `totalcost` field belong here.

**Does not own:** Authentication (`STATZWeb/decorators.py`), base navigation (`templates/base_template.html`), or the `crispy_forms` / jQuery UI libraries that the form and templates depend on.

**Classification:** Small, self-contained operational app with no cross-app model dependencies. No other installed app imports from `inventory`. The only external coupling is navigation links in `base_template.html` and the project-level URL include in `STATZWeb/urls.py`.

---

## 3. Read This Before Editing

### Before changing models
- `inventory/models.py` — verify the existing `save()` override and the mis-indented `__str__` (it sits inside `Meta` and never executes)
- `inventory/migrations/` — review the four existing migrations before any schema change
- `inventory/forms.py` — `InventoryItemForm` hard-codes `exclude = ['id', 'totalcost']`
- `inventory/templates/inventory/dashboard.html` — `data-sort` attribute values must match model field names exactly
- `inventory/templates/inventory/item_form.html` — label overrides use raw Django label strings (`"Nsn"`, `"Partnumber"`, `"Itemlocation"`, `"Purchaseprice"`) which derive from field names

### Before changing views
- `inventory/views.py` — note which views have `@conditional_login_required` and which do not (`autocomplete_*`, `delete_item_ajax`)
- `STATZWeb/decorators.py` — understand `conditional_login_required` behavior before adding or removing the decorator
- `inventory/urls.py` — confirm URL names used in JS (`inventory:delete_item`, `inventory:edit_item`, `inventory:add_item`, autocomplete endpoints)

### Before changing forms
- `inventory/forms.py` — `BaseFormMixin` injects CSS classes; `InventoryItemForm.__init__` also manually overrides widget classes for `nsn`, `description`, and `manufacturer` after the mixin runs
- `inventory/templates/inventory/item_form.html` — the template renders fields manually with `{% for field in form %}` and applies autocomplete CSS classes based on `field.name` — not crispy layout

### Before changing templates
- `inventory/templates/inventory/dashboard.html` — contains ~140 lines of inline JS (sort logic, modal lifecycle, AJAX delete); changes to column count or field names will break `getColumnIndex()`
- `inventory/templates/inventory/item_form.html` — label comparison strings (`"Nsn"`, `"Purchaseprice"`, etc.) are derived from Django's auto-capitalization of the field name; renaming a field changes these strings
- `templates/base_template.html` — contains two `{% url 'inventory:dashboard' %}` links (desktop nav line ~297, mobile menu line ~323); if the URL name changes, update both

---

## 4. Local Architecture / Change Patterns

This app is a flat, legacy-style Django app with no service layer:

- **Business logic lives in `models.py` and `views.py` only.** There are no services, selectors, or managers.
- **`InventoryItem.save()` is the only domain logic** — it recalculates `totalcost = purchaseprice * quantity`. This must stay in sync with any field changes.
- **Templates are not thin.** `dashboard.html` contains substantial inline JavaScript for client-side sorting and modal-based AJAX delete. Treat it as a coupled UI component, not a simple render target.
- **`item_form.html` bypasses crispy layout.** Despite `InventoryItemForm` wiring a crispy `Layout`, the template iterates `{% for field in form %}` and renders fields manually. The crispy `FormHelper` is wired but effectively ignored by the template.
- **Admin is minimal.** `admin.py` registers `InventoryItem` with no customizations.

---

## 5. Files That Commonly Need to Change Together

### Adding or renaming a model field
`inventory/models.py` → `inventory/migrations/` (new migration) → `inventory/forms.py` (update `exclude` or field list) → `inventory/templates/inventory/dashboard.html` (add column + `data-sort` attribute, update `getColumnIndex` JS logic) → `inventory/templates/inventory/item_form.html` (add field row, update label override conditionals if the label string changes)

### Renaming a URL or view
`inventory/urls.py` → `inventory/views.py` → `inventory/templates/inventory/dashboard.html` (JS `fetch` uses `{% url 'inventory:delete_item' 0 %}`) → `inventory/templates/inventory/item_form.html` (autocomplete `source` URLs, back-button href) → `templates/base_template.html` (nav links to `inventory:dashboard`)

### Changing autocomplete behavior
`inventory/views.py` (`autocomplete_nsn`, `autocomplete_description`, `autocomplete_manufacturer`) → `inventory/urls.py` (URL names) → `inventory/templates/inventory/item_form.html` (jQuery `source:` URLs and CSS class selectors) → `inventory/forms.py` (widget CSS classes `autocomplete-nsn`, `autocomplete-description`, `autocomplete-manufacturer`)

### Changing `totalcost` calculation
`inventory/models.py` (`save()`) → `inventory/views.py` (`dashboard()` re-computes total in Python) → `inventory/templates/inventory/dashboard.html` (renders `item.totalcost` and `total_inventory_value`)

---

## 6. Cross-App Dependency Warnings

**This app depends on:**
- `STATZWeb/decorators.py` — `conditional_login_required` is imported directly in `views.py`
- `STATZWeb/settings.py` — `REQUIRE_LOGIN` flag controls whether the decorator enforces auth
- `STATZWeb/urls.py` — includes `inventory.urls` under `/inventory/`
- `templates/base_template.html` — base layout; must load jQuery and jQuery UI for autocomplete and the `$(document).ready()` block in `item_form.html`
- `crispy_forms` — used in `forms.py` but effectively bypassed by the template's manual field rendering

**Other apps that depend on this app:**
- No Python-level imports from `inventory` found in any other app.
- `templates/base_template.html` reverses `inventory:dashboard` in two nav entries. Changing the URL name or app_name breaks global navigation for all users.

**No shared models or FK references** to `InventoryItem` exist in any other app.

---

## 7. Security / Permissions Rules

- `dashboard`, `add_item`, `edit_item`, and `delete_item` are protected by `@conditional_login_required`. Do not remove this decorator without understanding `settings.REQUIRE_LOGIN`.
- `delete_item_ajax` (`/inventory/delete-item-ajax/<pk>/`) has **no authentication decorator**. It is a live destructive endpoint accessible without login. Do not route clients to it; do not add features to it without first adding the decorator.
- The three autocomplete endpoints are also unauthenticated. They return data from the live database. If `REQUIRE_LOGIN` is not set project-wide, they expose all NSN, description, and manufacturer values publicly.
- The AJAX delete in `dashboard.html` posts with `X-CSRFToken` using `credentials: 'same-origin'`. Any CSRF middleware changes must preserve this contract.

---

## 8. Model and Schema Change Rules

- `InventoryItem` maps to legacy table `STATZ_WAREHOUSE_INVENTORY_TBL`. The `db_table` must not be changed without a migration and DBA coordination.
- Each field has an explicit `db_column` mapping (e.g., `db_column='NSN'`, `db_column='TotalCost'`). Renaming a field requires updating both the Python attribute name and the `db_column` if the column name must stay the same.
- `totalcost` is `editable=False` and excluded from `InventoryItemForm`. Do not add it to the form or remove it from `exclude` without updating the `save()` override intent.
- `save()` will raise `TypeError` if either `purchaseprice` or `quantity` is `None` at save time. Both fields allow null at the DB and form level. Adding non-null constraints requires a data migration.
- The `__str__` method in `models.py` is indented inside `Meta` and never executes. Fix it by dedenting it to be a direct method of `InventoryItem`. This is a known bug.
- Always run `makemigrations` and `migrate` after field changes. Four migrations already exist; new ones must chain cleanly.

---

## 9. View / URL / Template Change Rules

- URL names `dashboard`, `add_item`, `edit_item`, `delete_item`, `autocomplete_nsn`, `autocomplete_description`, `autocomplete_manufacturer`, `delete_item_ajax` are all referenced by string in templates. Renaming any of them requires searching templates and `base_template.html`.
- `dashboard.html` builds the AJAX delete URL at render time using `{% url 'inventory:delete_item' 0 %}` with a `.replace('0', deleteItemId)` pattern in JavaScript. If the URL pattern for `delete_item` changes its integer argument position, this breaks.
- Client-side sorting in `dashboard.html` uses `data-sort` attribute values that must exactly match model field names (`nsn`, `description`, `partnumber`, `manufacturer`, `itemlocation`, `quantity`, `purchaseprice`, `totalcost`). Adding a column requires adding both the `<th data-sort="fieldname">` header and the matching `<td>` in the row loop.
- `item_form.html` applies label overrides using exact string comparisons against Django's auto-generated labels (`"Nsn"`, `"Partnumber"`, `"Itemlocation"`, `"Purchaseprice"`). If field names change, these comparisons must be updated.
- The form template renders `{% for field in form %}` in field definition order. The crispy `Layout` in `forms.py` does not control rendering here.

---

## 10. Forms / Serializers / Input Validation Rules

- `InventoryItemForm` has no `clean()` logic. All nullable fields pass with empty input. The only server-side enforcement is the `save()` multiplication.
- `BaseFormMixin._style_fields()` runs first and sets widget classes; `InventoryItemForm.__init__` then overrides `nsn`, `description`, and `manufacturer` widget classes. If you change the mixin's class names, the autocomplete classes in the override will still win.
- The Submit button label in `FormHelper` reads `'Add Item'` — the template overrides this with its own "Save Item" button, so the crispy submit is never rendered.
- No serializers exist in this app.

---

## 11. Background Tasks / Signals / Automation Rules

None. No Celery tasks, signals, management commands, or scheduled jobs exist in this app. All behavior is synchronous and request-driven.

---

## 12. Testing and Verification Expectations

`inventory/tests.py` is an empty stub. There is zero automated coverage.

**After any change, manually verify:**
1. Navigate to `/inventory/` — dashboard renders, total value displays correctly.
2. Click column headers — client-side sorting works, Clear Sorting restores order.
3. Click Delete on a row — modal appears with correct NSN; confirm deletes the row and reloads.
4. Click the `+` button — add form opens, autocomplete works on NSN, Description, and Manufacturer fields.
5. Click Edit on a row — edit form pre-populates, saving redirects back to dashboard with updated data.
6. Verify `/admin/inventory/inventoryitem/` renders correctly.
7. If `totalcost` logic changed: add/edit an item with known values and confirm the stored `totalcost` equals `quantity × purchaseprice`.

---

## 13. Known Footguns

- **`__str__` is dead code.** `InventoryItem.__str__` is inside `Meta`. Django admin and shell will show the default `InventoryItem object (pk)`. Fixing requires moving it out of `Meta`. Do not add code that depends on `str(item)` producing a useful value until this is fixed.
- **`save()` crashes on null inputs.** `self.totalcost = self.purchaseprice * self.quantity` raises `TypeError` if either is `None`. The form allows both fields to be blank. This is an existing risk — do not make it worse by loosening validation elsewhere.
- **`delete_item_ajax` is an unauthenticated destructive endpoint.** It exists at a real URL and accepts POST. No client currently uses it, but it is live.
- **Dashboard JS column sorting is position-sensitive.** `getColumnIndex` counts `th[data-sort]` headers in DOM order. Inserting or removing a column without updating both the header and the row `<td>` order will silently sort the wrong column.
- **Autocomplete endpoints are unauthenticated.** They read from the live database. This is low-risk for read operations but leaks data if the app is exposed publicly.
- **`base_template.html` has two hardcoded `inventory:dashboard` links.** If you change the app_name or rename the view, navigation breaks globally for all users.
- **`item_form.html` label comparisons are fragile.** They check `field.label == "Nsn"` etc. Django generates labels from field names; this works until a `verbose_name` is added to the field, at which point the comparison silently fails and the label reverts to Django's auto-value.
- **`delete_form.html` is orphaned.** No view renders it. Do not mistake it for the active delete flow; the real delete is AJAX via `delete_item`.

---

## 14. Safe Change Workflow

1. Read `inventory/CONTEXT.md` and this file.
2. Read the specific files involved in your change (models, views, forms, or templates).
3. Search `templates/base_template.html` for any URL names you plan to rename.
4. Make the minimal scoped change.
5. Update all coupled files in the same edit (see Section 5).
6. If you changed model fields: create a migration and trace `dashboard.html` column headers/JS sort keys.
7. If you changed URL names: update all template `{% url %}` references.
8. Manually verify the flows listed in Section 12.
9. Note any new null-handling risk introduced near `save()`.

---

## 15. Quick Reference

| Area | Primary Files |
|---|---|
| Model + schema | `inventory/models.py`, `inventory/migrations/` |
| CRUD views | `inventory/views.py` |
| URL names | `inventory/urls.py` |
| Form + styling | `inventory/forms.py` |
| Dashboard UI + JS | `inventory/templates/inventory/dashboard.html` |
| Add/Edit form UI | `inventory/templates/inventory/item_form.html` |
| Currency formatting | `inventory/templatetags/custom_filters.py` |
| Auth decorator | `STATZWeb/decorators.py` |
| Global nav links | `templates/base_template.html` (lines ~297, ~323) |

**Main coupled areas:** model field names ↔ dashboard `data-sort` attributes ↔ JS `getColumnIndex` ↔ `item_form.html` label overrides

**Main cross-app dependencies:** `STATZWeb/decorators.py` (auth), `templates/base_template.html` (nav), `STATZWeb/urls.py` (include)

**Security-sensitive areas:** `@conditional_login_required` on CRUD views; `delete_item_ajax` and autocomplete endpoints lack it

**Riskiest edit types:**
- Renaming model fields (cascades into migrations, templates, JS sort keys, label comparisons)
- Changing URL names (breaks JS AJAX fetch, nav links, form back-buttons)
- Adding null guards to `save()` (required but currently missing)
- Touching the inline JS in `dashboard.html` (sort + modal are tightly coupled)


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
