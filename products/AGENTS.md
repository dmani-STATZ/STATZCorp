# AGENTS.md — `products`

Read `products/CONTEXT.md` first. This file complements it with concrete safe-edit rules grounded in the actual repository. It does not repeat the context file.

---

## 1. Purpose of This File

Defines how to safely modify the `products` app for AI coding agents and developers. The app is thin by design — it is a **model/URL carrier**, not a feature module. Most of the risk is in downstream consumers that import `Nsn` directly.

---

## 2. App Scope

**Owns:**
- `Nsn` model (stored in legacy table `contracts_nsn`)
- `SupplierNSNCapability` through-model (table `supplier_nsn_capability`)
- `AuditModel` abstract base
- URL namespace `products` with two shim routes: `nsn_edit` and `nsn_search`
- Admin registrations for both models
- `templates/products/nsn_edit.html`

**Does NOT own:**
- NSN editing or search view logic — lives in `contracts/views/nsn_views.py` and `contracts/views/idiq_views.py`
- NSN form definition — lives in `contracts/forms.py`
- NSN API endpoint — lives in `contracts/views/api_views.py`
- Any business logic beyond audit timestamps
- No services, signals, tasks, or management commands

This app is **glue/domain infrastructure**. Treat `models.py` and `migrations/` as the blast radius for most change types.

---

## 3. Read This Before Editing

### Before changing `models.py` fields
- `contracts/forms.py` — `NsnForm` lists every editable field explicitly
- `contracts/views/nsn_views.py` — `NsnUpdateView` context keys
- `contracts/views/idiq_views.py` — `NsnSearchView` queryset filter fields (`nsn_code`, `description`)
- `contracts/views/api_views.py` — `get_select_options` response shape for NSN autocomplete
- `contracts/views/dd1155_views.py` — imports and uses `Nsn` fields directly
- `contracts/models.py` — `Clin` and `IdiqContractDetails` have FKs to `Nsn`
- `contracts/management/commands/refresh_nsn_view.py` — references table/column names
- `contracts/utils/contracts_schema.py` — hardcodes `contracts_nsn` column references in schema descriptions
- `reports/views.py` line 34 — includes `'contracts_nsn'` in a table list
- `SQL/migrate_data.sql` — raw SQL inserts/reseeds against `contracts_nsn` by column name
- `contracts/migrations/0001_initial.py` and `.bak` — raw SQL views reference `contracts_nsn` columns
- `processing/views/processing_views.py` and `processing/views/matching_views.py` — both import and query `Nsn`

### Before changing `urls.py`
- Search the entire repo for `products:nsn_edit` and `products:nsn_search` (currently no template references found, but verify before renaming)
- The two URL names are shims; renaming them breaks any `reverse()` call or `{% url %}` tag using those names

### Before changing `templates/products/nsn_edit.html`
- `contracts/forms.py` — `NsnForm` field list must match the template sections
- `contracts/includes/simple_field.html` — the template depends on this partial
- `contracts/contract_base.html` — the template extends this base

### Before changing `admin.py`
- Safe to change display/search fields, but do not remove model registrations — staff rely on NSN search in admin

---

## 4. Local Architecture / Change Patterns

- **`products` is a thin domain app.** It defines models and wires URLs. It does not orchestrate anything.
- All business logic, form validation, view behaviour, and JS integration live in `contracts`.
- `AuditModel.save()` is the only active code: it sets `created_on` on first save and always updates `modified_on`. Do not remove or bypass this.
- There are no services, selectors, signals, tasks, or managers. Do not add them unless there is a clear reason — adding logic here can create circular import risks with `contracts`.
- The URL file directly imports from `contracts.views`. Any new URL added here must also import its view from elsewhere (this app has no views of its own).

---

## 5. Files That Commonly Need to Change Together

| Change | Files that move together |
|---|---|
| Add/rename a field on `Nsn` | `products/models.py`, `products/migrations/`, `contracts/forms.py`, `contracts/views/nsn_views.py`, `contracts/views/idiq_views.py`, `contracts/views/api_views.py`, `contracts/utils/contracts_schema.py`, `templates/products/nsn_edit.html`, any affected `contracts/templates/` |
| Add/rename a field on `SupplierNSNCapability` | `products/models.py`, `products/migrations/`, `products/admin.py` |
| Change `nsn_code` or `description` specifically | All of the above + `contracts/views/idiq_views.py` (search filter), `contracts/views/api_views.py` (select options), `SQL/migrate_data.sql` |
| Add a new NSN URL | `products/urls.py` + the view file in `contracts/views/` it points to |

---

## 6. Cross-App Dependency Warnings

### This app depends on:
- `suppliers.models.Supplier` — FK target for `SupplierNSNCapability` and the M2M on `Nsn`. Supplier deletions cascade to `SupplierNSNCapability` rows via `CASCADE`.
- `django.contrib.auth.models.User` — FK target for `AuditModel` audit fields (SET_NULL on delete).

### Apps that depend on this app:
| App | What it imports/uses |
|---|---|
| `contracts` | `Nsn` in `models.py`, `forms.py`, `nsn_views.py`, `idiq_views.py`, `dd1155_views.py`, `api_views.py`, management command, schema util, and multiple templates |
| `processing` | `Nsn` in `processing_views.py` and `matching_views.py` — used in CLIN matching logic |
| `reports` | References `'contracts_nsn'` table name directly in `views.py` |

### Legacy table name coupling:
- `contracts_nsn` and `supplier_nsn_capability` are hardcoded in `db_table`. These names appear in:
  - `contracts/utils/contracts_schema.py`
  - `contracts/migrations/0002_create_views.py.bak` (raw SQL views)
  - `reports/views.py`
  - `SQL/migrate_data.sql` (multiple raw SQL statements with column-level references)

  **Do not rename these tables without updating all raw SQL and the reports view.**

---

## 7. Security / Permissions Rules

- `NsnUpdateView` (in `contracts`) is wrapped with `conditional_login_required`. Do not expose the `products:nsn_edit` URL without that decorator in place on the target view.
- `NsnSearchView` (in `contracts`) uses `LoginRequiredMixin` and enforces `len(query) >= 3`. Do not modify the URL mapping in a way that bypasses or replaces the view with an unauthenticated equivalent.
- `AuditModel` fields track who created/modified NSN records. Do not override `save()` in a way that skips the parent call or clears `created_by`/`modified_by`.
- No object-level ACL exists in `products`. Any permission tightening must happen in the `contracts` views this app routes to.

---

## 8. Model and Schema Change Rules

- **Before renaming any `Nsn` field**, run a repo-wide search for the field name (e.g., `nsn_code`, `description`, `part_number`, `revision`, `notes`, `directory_url`). It will appear in:
  - `contracts/forms.py` (form `fields` list)
  - `contracts/views/idiq_views.py` (queryset filter `__icontains`)
  - `contracts/views/api_views.py` (select options response)
  - `contracts/utils/contracts_schema.py` (schema description string)
  - `SQL/migrate_data.sql` (column-level INSERT statements)
  - `templates/products/nsn_edit.html` and contracts templates

- **`db_table` values are locked.** `contracts_nsn` and `supplier_nsn_capability` must not be changed without a coordinated update of all raw SQL references listed in section 6.

- **`SupplierNSNCapability` has a `CASCADE` delete from both `Nsn` and `Supplier`.** Deleting an `Nsn` removes all its capability rows silently. This is intentional but worth verifying in any data-cleanup work.

- **`AuditModel.modified_on` uses `auto_now=True` on the field and also sets it manually in `save()`.** This double-setting is redundant but harmless. Do not remove the `save()` override — it also handles `created_on`.

- The sole migration is `products/migrations/0001_initial.py` and uses `SeparateDatabaseAndState`. Do not alter the state operations without understanding why — the table already existed in the database when this was written.

- When adding new fields, always check whether `contracts/forms.py` `NsnForm` needs a matching addition and whether `nsn_edit.html` needs a new section.

---

## 9. View / URL / Template Change Rules

- `products/views.py` is intentionally empty. Do not add views here without a clear reason — existing patterns put NSN views in `contracts`.
- The two URL names (`products:nsn_edit`, `products:nsn_search`) are confirmed not reversed in templates currently, but search before renaming.
- `templates/products/nsn_edit.html` depends on:
  - `contracts/contract_base.html` (extends)
  - `contracts/includes/simple_field.html` (include — used for every form field)
  - `NsnForm` field names as context keys
- If a new NSN template is needed, follow the same pattern: extend `contracts/contract_base.html` and use `simple_field.html` for field rendering.

---

## 10. Forms / Serializers / Input Validation Rules

- No forms are defined in `products`. All input handling for `Nsn` lives in `contracts/forms.py` (`NsnForm`).
- Do not add form logic here — it would create a split between where the form is defined and where it is used, complicating future changes.
- If `NsnForm` validation needs to change, edit `contracts/forms.py` and update `templates/products/nsn_edit.html` and `contracts/views/nsn_views.py` together.

---

## 11. Background Tasks / Signals / Automation Rules

None. There are no signals, Celery tasks, periodic jobs, or management commands in `products`. The only automated behaviour is the `AuditModel.save()` timestamp logic.

Note: `contracts/management/commands/refresh_nsn_view.py` is in the `contracts` app but touches the `contracts_nsn` table. Inspect it before any schema change.

---

## 12. Testing and Verification Expectations

`products/tests.py` is empty (placeholder only). There are no dedicated tests for this app.

After editing, verify manually:
1. **Admin:** open `/admin/products/nsn/` — confirm list display, search, and edit form load without errors.
2. **NSN edit flow:** navigate to `/products/nsn/<pk>/edit/` — confirm the form renders, saves, and redirects correctly.
3. **NSN search:** call `/products/nsn/search/?q=<3chars>` — confirm JSON response returns `id`/`text` pairs.
4. **CLIN form autocomplete:** open a CLIN form in `contracts` and verify the NSN select widget populates.
5. **IDIQ detail page:** confirm NSN display on an IDIQ contract detail page is intact.
6. **Processing:** if `Nsn` fields were changed, verify `processing` matching views still filter correctly.
7. **Reports:** if the `contracts_nsn` table name or column set changed, verify `reports/views.py` still works.
8. Run the `contracts` test suite — it provides the only automated coverage for NSN behavior.

---

## 13. Known Footguns

- **`contracts_nsn` table name is referenced in raw SQL in four places** (`contracts_schema.py`, migration `.bak`, `reports/views.py`, `SQL/migrate_data.sql`). A model rename or `db_table` change without updating all of these will silently break reports and schema descriptions.

- **`Nsn` fields appear in `SQL/migrate_data.sql` INSERT column lists.** Adding a NOT NULL field without a default will break the SQL migration script even if Django migrations succeed.

- **`AuditModel.modified_on` is set both by `auto_now=True` and by `save()`.** The `save()` call is redundant for this field but guards `created_on`. If someone refactors to remove the `save()` override, `created_on` will stop being set correctly on first save.

- **`processing` app imports `Nsn` for matching logic.** Field renames on `Nsn` will silently break matching if `processing` views are not updated in the same change.

- **`NsnSearchView` is in `contracts/views/idiq_views.py`** (not `nsn_views.py`). The name is counterintuitive — search here if NSN search behaviour needs changing.

- **No uniqueness constraint on `nsn_code`.** The field is `null=True, blank=True`. Duplicate or blank NSN codes are possible and will appear in search results.

- **`SupplierNSNCapability` has no documented creation path.** The admin is the only confirmed way to create rows. Do not assume they exist when writing logic that reads `lead_time_days` or `price_reference`.

- **Circular import risk:** `products.models` imports `suppliers.models.Supplier`. Any attempt to import `contracts` models from `products` would likely create a circular import chain (`products → contracts → products`). Do not add such imports.

---

## 14. Safe Change Workflow

1. Read `products/CONTEXT.md` and this file.
2. Read `products/models.py` to confirm current field names.
3. For any field change: search repo-wide for the field name before touching anything.
4. For URL changes: search repo-wide for the URL name (`products:nsn_edit`, `products:nsn_search`).
5. Make the minimal change in `products/models.py`.
6. Generate and review the migration — confirm `SeparateDatabaseAndState` pattern is preserved if appropriate.
7. Update coupled files in `contracts/` (forms, views, templates, schema util) in the same change.
8. Update `SQL/migrate_data.sql` if column names changed.
9. Manually verify: admin NSN list/edit, NSN search endpoint, CLIN autocomplete, IDIQ detail.
10. Run the `contracts` test suite.
11. Summarise which downstream files were updated and which were checked and left unchanged.

---

## 15. Quick Reference

| Category | Details |
|---|---|
| Primary files | `products/models.py`, `products/migrations/0001_initial.py`, `products/urls.py` |
| Main coupled areas | `contracts/forms.py`, `contracts/views/nsn_views.py`, `contracts/views/idiq_views.py`, `contracts/views/api_views.py`, `contracts/utils/contracts_schema.py`, `templates/products/nsn_edit.html` |
| Cross-app dependents | `contracts` (heavy), `processing` (Nsn import), `reports` (table name), `SQL/migrate_data.sql` (column-level raw SQL) |
| Security-sensitive | `NsnUpdateView` login decorator, `NsnSearchView` login + query-length guard, `AuditModel` audit trail |
| Riskiest edits | Renaming any `Nsn` field, changing `db_table` values, adding NOT NULL fields without defaults, removing `AuditModel.save()` |
| App character | Thin model/URL carrier. Logic lives in `contracts`. Treat as infrastructure. |


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
