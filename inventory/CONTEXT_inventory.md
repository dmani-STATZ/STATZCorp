# Inventory Context

## 1. Purpose
The `inventory` app owns the warehouse stock ledger described in `inventory/Inventory Application.md`: it lets staff catalog every part by NSN, description, part number, manufacturer, location, quantity, and purchase price, then keep that catalog up to date with adds, edits, deletions, and autocomplete-assisted data entry while surfacing a single dashboard that shows total inventory value.

## 2. App Identity
- **Django app name:** `inventory` (see `inventory/apps.py`).
- **AppConfig:** `InventoryConfig` (inherits from `AppConfig`, sets `verbose_name = 'Inventory Management'`).
- **Filesystem path:** `inventory/` under the project root.
- **Classification:** Feature/operational app that powers an end-user inventory management UI anchored at `/inventory/` (included from `STATZWeb/urls.py`).

## 3. High-Level Responsibilities
- Persist the `InventoryItem` row (mapped to the legacy `STATZ_WAREHOUSE_INVENTORY_TBL`) and recalculate `totalcost` whenever a record is saved (`inventory/models.py`).
- Render an authenticated dashboard that lists every row, formats money via `custom_currency`, lets staff open add/edit forms, and triggers AJAX deletes and client-side sorting (`inventory/views.py`, `inventory/templates/inventory/dashboard.html`).
- Provide add/edit/delete views with a single `InventoryItemForm` (styling/placeholder mixin) plus jQuery UI autocomplete helpers to populate NSN, description, and manufacturer fields (`inventory/forms.py`, `inventory/templates/inventory/item_form.html`, `inventory/views.py`).
- Expose autocomplete and delete endpoints that return JSON so the dashboard and form templates can behave smoothly without full page reloads (`inventory/views.py`, `inventory/urls.py`).
- Register `InventoryItem` in the Django admin so staff can browse the raw table in `/admin` (`inventory/admin.py`).

## 4. Key Files and What They Do
- `apps.py`: Defines `inventory.apps.InventoryConfig` so the app appears as Inventory Management in admin and config.
- `models.py`: Declares `InventoryItem` (AutoField `id`, nullable text fields, integer quantity, float purchase price, computed `totalcost`, `Meta.db_table = 'STATZ_WAREHOUSE_INVENTORY_TBL'`, but note `__str__` is indented inside `Meta` and never executes).
- `forms.py`: Supplies `BaseFormMixin`/`BaseModelForm` for consistent placeholder/class styling plus `InventoryItemForm` that excludes `id`/`totalcost`, wires a `crispy_forms` layout, and tags `nsn`/`description`/`manufacturer` with autocomplete classes.
- `views.py`: Houses all UI endpoints (dashboard, add/edit/delete, delete AJAX, three autocomplete lookups); most views are wrapped with `@conditional_login_required` from `STATZWeb/decorators.py`.
- `urls.py`: Maps `/inventory/` to the views above, including separate paths for AJAX deletion plus the autocomplete endpoints.
- `admin.py`: Registers `InventoryItem` so it appears in Django admin with default options.
- `templates/inventory/dashboard.html`: Bootstrap-styled dashboard page that lists every inventory row, shows total value, formats money with `custom_currency`, and bundles inline JS for modal deletion + client-side sorting/clear-sorting controls.
- `templates/inventory/item_form.html`: Custom-styled add/edit form that reuses the same `InventoryItemForm`, applies bespoke row/label markup, and wires jQuery UI autocomplete to the three AJAX endpoints.
- `templates/inventory/delete_form.html`: Simple confirmation page (currently unused by any view but still in repo).
- `templatetags/custom_filters.py`: Defines `custom_currency` filter used to format `purchaseprice`, `totalcost`, and the dashboard total value.
- `Inventory Application.md`: App-level write-up already describes the CRUD/autocomplete/modals flows—useful reference when revisiting requirements.
- `migrations/`: Track schema history (initial create, then `0002`/`0003`/`0004` renamed/altered description/purchase price/total cost columns).

## 5. Data Model / Domain Objects
- **`InventoryItem`** maps to the legacy `STATZ_WAREHOUSE_INVENTORY_TBL`. It declares `id` (AutoField), `nsn`, `description`, `partnumber`, `manufacturer`, and `itemlocation` as nullable `CharField`s; `quantity` as nullable `IntegerField`; `purchaseprice` as nullable `FloatField`; and `totalcost` as a nullable `FloatField` that is marked `editable=False` and recalculated in `save()` as `purchaseprice * quantity`.
- The `save()` override recalculates `totalcost` on every write but does not guard against `None`, so updating with missing `quantity` or `purchaseprice` would raise `TypeError` unless callers validate before saving.
- The attempted `__str__` method sits inside the `Meta` class definition and therefore never binds to the model; no human-readable string exists unless that indentation is corrected.
- There are no explicit `ForeignKey`s to other apps; this app solely owns the inventory table and reuses only primitive fields.

## 6. Request / User Flow
- **Dashboard (`/inventory/` or `/inventory/dashboard`):** `dashboard()` pulls all `InventoryItem` rows, sums `item.quantity * item.purchaseprice` in Python, and renders `dashboard.html`. The template shows the list, total value, and renders the modal+buttons for deletion (AJAX) plus column headers that toggle client-side sorting.
- **Add item (`/inventory/add/`):** `add_item()` instantiates `InventoryItemForm`. On POST, it saves a new row and redirects back to the dashboard; on GET, it renders `item_form.html` with the form.
- **Edit item (`/inventory/edit/<pk>/`):** `edit_item()` finds the existing row, pre-fills the form, saves changes on POST, and redirects back.
- **Delete item (`/inventory/delete-item/<pk>/`):** `delete_item()` requires POST, deletes the row, and returns `{'success': True}`. Dashboard JavaScript hits this path via `fetch` (with CSRF token) after a modal confirmation. A separate `delete_item_ajax()` view duplicates the logic without the decorator and is wired to `/delete-item-ajax/<pk>/` (but the dashboard currently targets the non-AJAX path).
- **Autocomplete:** Three JSON endpoints (`/autocomplete/nsn/`, `/autocomplete/description/`, `/autocomplete/manufacturer/`) return up to 10 distinct matches based on the search term; the form template mounts them via jQuery UI to power type-ahead inputs.

## 7. Templates and UI Surface Area
- Templates extend `base_template.html`, so the app inherits the global navigation, scripts, and styles defined in `templates/base_template.html` (which already links to `inventory:dashboard` from the main nav and mobile menu).
- `dashboard.html` renders a Bootstrap-styled table with columns for every inventory field, a large total value display, and a modal for confirm deletions. Inline `<style>` defines sort-state indicators, and `<script>` handles the modal lifecycle, AJAX delete, and client-side sorting/ordering with a `Clear Sorting` toggle.
- `item_form.html` renders the same form for both adds and edits. It writes per-field labels (with manual overrides for NSN/Part Number/Location/Purchase Price), styles inputs with custom `.input-field` classes, and initializes autocomplete widgets inside a jQuery `$(document).ready()` block, which implies the base template must load jQuery/jQuery UI.
- `delete_form.html` is a legacy form-only confirmation screen that is not referenced in any view, suggesting either retired logic or a shortcut for manual testing.

## 8. Admin / Staff Functionality
`admin.site.register(InventoryItem)` exposes the table through Django’s default admin interface with no customizations beyond the registration listed in `admin.py`.

## 9. Forms, Validation, and Input Handling
- `BaseFormMixin` injects consistent CSS classes and placeholders for text, number, select, textarea, and checkbox widgets when forms instantiate.
- `InventoryItemForm` extends `BaseModelForm`, excludes `id`/`totalcost`, wires a `crispy_forms.FormHelper` layout that groups fields inside a single `Fieldset` with `Column` widgets, and adds a `Submit` button labeled “Add Item.”
- The form also tags `nsn`, `description`, and `manufacturer` widgets with `autocomplete-*` CSS classes so the template can attach the correct AJAX source.
- No custom `clean()` logic exists, so validation relies on the nullable `CharField` and `FloatField` defaults; the save-time multiplication is the only enforcement of `totalcost` integrity.

## 10. Business Logic and Services
- All business logic lives in `views.py` and `models.py`. `InventoryItem.save()` ensures `totalcost` always equals `purchaseprice * quantity`.
- `dashboard()` computes `total_inventory_value` by iterating the queryset client-side rather than using Django aggregates, then passes the raw rows to `dashboard.html`.
- `add_item()`/`edit_item()` reuse `InventoryItemForm`; the views redirect to the dashboard on success.
- Deletion is handled by `delete_item()` (decorated with `@conditional_login_required`) and the redundant `delete_item_ajax()`.
- Autocomplete helpers (`autocomplete_nsn`, `autocomplete_description`, `autocomplete_manufacturer`) use `.values_list(...).distinct()[:10]` to feed the form widgets.
- There are no separate service, selectors, or Celery modules; `inventory` keeps its logic grouped around these few functions.

## 11. Integrations and Cross-App Dependencies
- `STATZWeb/urls.py` includes `inventory.urls` under `/inventory/`, so the app is wired to the main routing tree.
- Templates extend `templates/base_template.html`, which renders the global navigation entry for Inventory and presumably loads the JS (jQuery, Bootstrap, etc.) that the app’s templates expect.
- `dashboard`, `add_item`, `edit_item`, and `delete_item` are decorated with `conditional_login_required` from `STATZWeb/decorators.py`, which checks `settings.REQUIRE_LOGIN` before applying Django’s `login_required`. The decorator and views both rely on the `REQUIRE_LOGIN` sentinel documented in `STATZWeb/settings.py`.
- The form module depends on `crispy_forms` components (`FormHelper`, `Layout`, `Fieldset`, `Column`, `Submit`) to assemble the UI.
- Templates load `custom_filters` (`custom_currency`), defined locally under `templatetags/custom_filters.py`, to format monetary values.
- The inline scripts in `item_form.html` assume jQuery UI’s `.autocomplete` is available, so changes to the base template’s JS stack may break the form.
- AJAX delete code in `dashboard.html` posts to `/inventory/delete-item/<pk>/` and sends the CSRF token, so any changes to CSRF middleware configuration must preserve that contract.

## 12. URL Surface / API Surface
- `POST /inventory/delete-item/<pk>/`: Deletes the item and returns `{'success': True}` (`views.delete_item`).
- `POST /inventory/delete-item-ajax/<pk>/`: Duplicate path hooked to `delete_item_ajax` (but the dashboard currently hits the non-AJAX view).
- `GET /inventory/autocomplete/nsn/`: Returns JSON list of matching NSNs for the add/edit form.
- `GET /inventory/autocomplete/description/`: Returns JSON list of matching descriptions.
- `GET /inventory/autocomplete/manufacturer/`: Returns JSON list of matching manufacturers.
- `GET /inventory/` and `/inventory/dashboard`: Entry dashboard showing the table and total value.
- `GET /inventory/add/`: Renders the `InventoryItemForm` for new rows; POST saves.
- `GET /inventory/edit/<pk>/`: Renders the form for an existing row; POST saves edits.

## 13. Permissions / Security Considerations
- The key UI flows (`dashboard`, `add_item`, `edit_item`, `delete_item`) are wrapped with `@conditional_login_required`, so they require authentication whenever `settings.REQUIRE_LOGIN` evaluates to `True` (see `STATZWeb/settings.py`).
- Autocomplete endpoints and `delete_item_ajax()` are **not** decorated, so they respond to any request; the autocomplete views simply read and return data, but `delete_item_ajax` exposes a destructive path without the login guard—a risk if this URL is ever favored by clients.
- The AJAX delete call in `dashboard.html` posts with `X-CSRFToken` and uses `credentials: 'same-origin'`, so any changes to CSRF middleware configuration must preserve that behavior.
- `InventoryItem.save()` multiplies `quantity` and `purchaseprice` even though both fields allow `null`, so enforcing non-null input at the form, view, or database level should precede such calculations to avoid `TypeError` explosions.

## 14. Background Processing / Scheduled Work
None. No Celery tasks, management commands, signals, or scheduled jobs exist within this app.

## 15. Testing Coverage
`inventory/tests.py` is the default stub with no assertions or test cases, so there is currently zero automated coverage for this app.

## 16. Migrations / Schema Notes
- Four migrations exist under `inventory/migrations/0001_*` through `0004_*`, showing an initial create plus incremental adjustments to `description`, `purchaseprice`, and `totalcost` columns only a few commits after the initial migration.
- The schema uses the legacy `STATZ_WAREHOUSE_INVENTORY_TBL`, so any field renames or type changes must maintain compatibility with that table name and the historical migration history.

## 17. Known Gaps / Ambiguities
- The `__str__` method is indented under `Meta` in `models.py`, so Django never registers it; the model prints the default `Model.__str__` unless this is realigned.
- `delete_form.html` exists but no view renders it anymore; it may be a remnant of a previous POST-confirmation flow.
- `delete_item_ajax()` duplicates `delete_item()` but lacks authentication; if this endpoint is exposed, it bypasses `conditional_login_required`.
- Autocomplete views, despite returning only strings, are unauthenticated and could expose the full set of NSNs/manufacturers unless `REQUIRE_LOGIN` is set at the project level.
- The dashboard’s total value computation (`sum(item.quantity * item.purchaseprice)`) and the `InventoryItem.save()` multiplication both assume non-null numeric inputs even though the form allows blanks.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- When editing `InventoryItem` fields, keep `totalcost` in sync: update the `save()` override, the form's `exclude`, and any dashboard calculations together.
- Touching `inventory/templates/inventory/dashboard.html` requires revalidating the inline JS (modal lifecycle, AJAX fetch URL, `clearSort` button) and the `custom_currency` filter; the template relies on the `delete_item` URL name and a CSRF token rendered by Django.
- The add/edit form depends on jQuery UI’s autocomplete hooks and the three JSON endpoints. If you rename or change those URLs, update the selectors in `item_form.html` and the AJAX views in `views.py` simultaneously.
- Any changes to authentication should respect `conditional_login_required` and `settings.REQUIRE_LOGIN`; if you need to expose one of the endpoints to other services, decide intentionally whether to decorate it.
- Because `base_template.html` contributes the navigation entry, update it if you change the app’s URL prefix.

## 19. Quick Reference
- **Primary model:** `InventoryItem` (`inventory/models.py`), tied to `STATZ_WAREHOUSE_INVENTORY_TBL` with computed `totalcost`.
- **Main URLs:** dashboard (`inventory/dashboard`), add/edit/delete (`inventory/add`, `inventory/edit/<pk>`, `inventory/delete-item/<pk>`), delete AJAX (`inventory/delete-item-ajax/<pk>`), autocomplete endpoints (`inventory/autocomplete/*`).
- **Key templates:** `inventory/templates/inventory/dashboard.html`, `inventory/templates/inventory/item_form.html`, `inventory/templates/inventory/delete_form.html`.
- **Key dependencies:** `STATZWeb/decorators.py` + `settings.REQUIRE_LOGIN`, `templates/base_template.html`, `crispy_forms`, `jQuery UI`, `templatetags/custom_filters.py`.
- **Risky files to review first:** `inventory/views.py` (decorators, delete + JSON endpoints), `inventory/templates/inventory/dashboard.html` (modal + sorting + AJAX), `inventory/models.py` (save calculation, mis-indented `__str__`).


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
