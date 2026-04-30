# AGENTS.md — `products`
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

Read `products/CONTEXT.md` first. This file complements it with concrete safe-edit rules grounded in the actual repository. It does not repeat the context file.

---

## 1. Purpose of This File

Defines how to safely modify the `products` app for AI coding agents and developers. The app is thin by design — it is a **model/URL carrier**, not a feature module. Most of the risk is in downstream consumers that import `Nsn` directly.

---

## 2. App Scope

**Owns:**
- `Nsn` model (stored in legacy table `contracts_nsn`), including the packout fields `unit_weight`, `unit_length`, `unit_width`, `unit_height`, and `packaging_notes` introduced in migration `0002_nsn_packout_fields`
- `SupplierNSNCapability` through-model (table `supplier_nsn_capability`)
- `AuditModel` abstract base
- URL namespace `products` with four routes: `nsn_edit` and `nsn_search` (shims into `contracts/views`) plus `nsn_detail` and `nsn_packout_update` (local to this app)
- Admin registrations for both models
- `templates/products/nsn_edit.html` and `templates/products/nsn_detail.html`
- Local views in `products/views.py`: `NsnDetailView` (DetailView for the read-focused detail page) and `nsn_packout_update` (POST-only JSON endpoint for inline packout editing)

**Does NOT own:**
- NSN edit/update form rendering — lives in `contracts/views/nsn_views.py` (`NsnUpdateView`)
- NSN search view logic — lives in `contracts/views/idiq_views.py` (`NsnSearchView`)
- NSN form definition — lives in `contracts/forms.py` (`NsnForm`); when packout fields change, both this form and `nsn_packout_update` validation must move together
- NSN API endpoint for select widgets — lives in `contracts/views/api_views.py`
- `sales.ApprovedSource` data — `products` reads this model from the NSN detail view (`get_approved_sources_data`) but does not own its schema, import logic, or admin. Any schema change to `ApprovedSource` (especially renaming `nsn`, `approved_cage`, `part_number`, `company_name`, or `import_batch`) is the sales app's responsibility, but it silently breaks the NSN detail page if the read site here is not updated in the same change.
- No services, signals, tasks, or management commands

This app started as **glue/domain infrastructure** but now also owns a real read-focused detail page and a small JSON packout endpoint. Treat `models.py`, `views.py`, `urls.py`, and `migrations/` as the blast radius for most change types.

---

## 3. Read This Before Editing

### Before changing `models.py` fields
- `contracts/forms.py` — `NsnForm` lists every editable field explicitly (including the packout fields `unit_weight`, `unit_length`, `unit_width`, `unit_height`, `packaging_notes`)
- `products/views.py` — `nsn_packout_update` enumerates the packout fields for inline JSON validation; adding/renaming a packout field requires editing the `_DECIMAL_FIELDS` tuple (or the `packaging_notes` branch) here
- `templates/products/nsn_detail.html` — the packout form posts the field names verbatim and the readout sections reference field attributes by name
- `contracts/views/nsn_views.py` — `NsnUpdateView` context keys
- `contracts/views/idiq_views.py` — `NsnSearchView` queryset filter fields (`nsn_code`, `description`)
- `contracts/views/api_views.py` — `get_select_options` response shape for NSN autocomplete
- `contracts/models.py` — `Clin` and `IdiqContractDetails` have FKs to `Nsn`
- `contracts/management/commands/refresh_nsn_view.py` — references table/column names
- `contracts/utils/contracts_schema.py` — auto-generates column descriptions from `concrete_fields`; hand-curated relationships still reference `contracts_nsn` FKs by name
- `reports/views.py` line 34 — includes `'contracts_nsn'` in a table list
- `SQL/migrate_data.sql` — raw SQL inserts/reseeds against `contracts_nsn` by column name (the column list now includes the packout columns)
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
| Add/rename a field on `Nsn` | `products/models.py`, `products/migrations/`, `contracts/forms.py`, `contracts/views/nsn_views.py`, `contracts/views/idiq_views.py`, `contracts/views/api_views.py`, `contracts/utils/contracts_schema.py`, `templates/products/nsn_edit.html`, `templates/products/nsn_detail.html`, any affected `contracts/templates/` |
| Add/rename a field on `SupplierNSNCapability` | `products/models.py`, `products/migrations/`, `products/admin.py` |
| Change `nsn_code` or `description` specifically | All of the above + `contracts/views/idiq_views.py` (search filter), `contracts/views/api_views.py` (select options), `SQL/migrate_data.sql` |
| Add/rename a packout field on `Nsn` | `products/models.py`, `products/migrations/`, `products/views.py` (`_DECIMAL_FIELDS` tuple or `packaging_notes` branch in `nsn_packout_update`), `contracts/forms.py` (`NsnForm.Meta.fields` and `widgets`), `templates/products/nsn_detail.html` (form input + readout), `templates/products/nsn_edit.html` if it lists fields explicitly, `SQL/migrate_data.sql` (column list + SELECT clause) |
| Add a new NSN URL | `products/urls.py` + the view file in `products/views.py` (or `contracts/views/`) it points to |
| Change to `ApprovedSource` fields used in detail page | `sales/models/approved_sources.py`, `products/views.py` (`get_approved_sources_data`), `templates/products/nsn_detail.html` (the approved-sources panel block) |

---

## 6. Cross-App Dependency Warnings

### This app depends on:
- `suppliers.models.Supplier` — FK target for `SupplierNSNCapability` and the M2M on `Nsn`. Supplier deletions cascade to `SupplierNSNCapability` rows via `CASCADE`. Also read by `NsnDetailView.get_approved_sources_data` via a single batched `Supplier.objects.filter(cage_code__in=...)` query to resolve approved-source CAGEs.
- `sales.models.ApprovedSource` — read by `NsnDetailView.get_approved_sources_data` via a lazy import. Joined to `Nsn` by string match on `nsn` ↔ `nsn_code` and to `Supplier` by string match on `approved_cage` ↔ `cage_code`. **No FKs in either direction.** Field name changes on `ApprovedSource` (especially `nsn`, `approved_cage`, `part_number`, `company_name`, `import_batch`) will silently break the NSN detail page.
- `django.contrib.auth.models.User` — FK target for `AuditModel` audit fields (SET_NULL on delete).

### Apps that depend on this app:
| App | What it imports/uses |
|---|---|
| `contracts` | `Nsn` in `models.py`, `forms.py`, `nsn_views.py`, `idiq_views.py`, `api_views.py`, management command, schema util, and multiple templates |
| `processing` | `Nsn` in `processing_views.py` and `matching_views.py` — used in CLIN matching logic |
| `reports` | References `'contracts_nsn'` table name directly in `views.py` |

### This app depends on (cross-cutting, beyond the rows above):
- `contracts.models.Clin` and `contracts.models.IdiqContractDetails` — lazy-imported inside `NsnDetailView.get_context_data` (not at module top-level) to avoid the circular `products → contracts → products` import chain. Any future view that needs `contracts` models must follow the same lazy-import pattern.

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

- `products/views.py` now owns `NsnDetailView` and `nsn_packout_update`. NSN edit/search still lives in `contracts/views`. Before adding new views to this app, read `AGENTS.md` § 13 footgun about lazy imports — `contracts.models` cannot be imported at module top-level.
- The four URL names (`products:nsn_edit`, `products:nsn_search`, `products:nsn_detail`, `products:nsn_packout_update`) are reversed in `templates/products/nsn_detail.html`. Search before renaming any of them.
- `templates/products/nsn_edit.html` depends on:
  - `contracts/contract_base.html` (extends)
  - `contracts/includes/simple_field.html` (include — used for every form field)
  - `NsnForm` field names as context keys
- `templates/products/nsn_detail.html` depends on:
  - `contracts/contract_base.html` (extends)
  - All `.nsn-detail-*` component classes in `static/css/app-core.css` and `--font-mono` in `static/css/theme-vars.css`
  - The context keys supplied by `NsnDetailView.get_context_data` (`nsn`, `supplier_capabilities`, `referencing_clins`, `referencing_idiq_details`, `has_packout_data`)
  - The reverse URLs `products:nsn_edit`, `products:nsn_packout_update`, `suppliers:supplier_detail`, `contracts:clin_detail`, `contracts:idiq_contract_detail` — if any of these get renamed the detail template breaks
- If a new NSN edit-style template is needed, follow `nsn_edit.html`: extend `contracts/contract_base.html` and use `simple_field.html`. If a new NSN read/scan template is needed, follow `nsn_detail.html`: extend the same base, but use the `.nsn-detail-*` prefix convention for new component classes and rely on Bootstrap CSS variables for colors so dark mode works without extra rules.

### Inline editing JS contract on `nsn_detail.html`

The packout panel ships its own inline `<script>` block (no separate JS module — vanilla, ~120 lines, lives at the bottom of the template). When changing the packout fields or the JSON endpoint, keep this contract intact:

- Each editable field is a real `<input>` or `<textarea>` wrapped in `<div class="nsn-detail-field" data-field="<field_name>">`. The wrapper's `data-state` attribute (`saving` / `saved` / `error`, or absent for idle) drives the per-field visual state via attribute selectors in `app-core.css`. **Don't replace the wrapper with a Bootstrap `.input-group` or similar — the attribute-selector CSS won't reach inside.**
- The script reads the panel's `data-update-url` and the `{% csrf_token %}` hidden input from the panel itself, then POSTs `{<field_name>: <value>}` JSON per field with `X-CSRFToken` and `X-Requested-With: XMLHttpRequest`. Adding a new packout field requires adding it to the `DECIMAL_FIELDS` map in the script (or to the textarea-style branch) AND adding it to `_DECIMAL_FIELDS` / the `packaging_notes` branch in `products/views.py` `nsn_packout_update`.
- Numeric fields debounce 400ms on `input` and flush on `blur`; Enter on a number input commits and blurs (Cmd/Ctrl+Enter for textarea). Empty input is sent as the empty string and clears the field server-side. The endpoint's `{ok, errors}` JSON shape is what drives the `saved` flash vs the inline error text — keep the response shape stable.
- The live calculator at the bottom of the panel is JS-only (no backend call). It reads from the same `<input>` IDs as the saved fields, so any rename of `nsn-f-unit_weight` / `nsn-f-unit_length` / `nsn-f-unit_width` / `nsn-f-unit_height` / `nsn-calc-qty` breaks the calculator silently.

### CSS prefix convention

All component classes for `nsn_detail.html` are prefixed `.nsn-detail-*` and live in `static/css/app-core.css`. New NSN-detail component classes must follow this prefix to stay scoped. Sub-features within the page get a sub-prefix: the approved-sources panel uses `.nsn-detail-source-*` (e.g., `.nsn-detail-source-row`, `.nsn-detail-source-chip`). Color values must come from existing tokens (Bootstrap `--bs-*` variables or `--company-primary` / `--company-secondary`); new hex values must be added to `static/css/theme-vars.css` first with a justifying comment.

### Resolution-chip pattern (approved-sources panel)

The "in our system" / "not in DB" indicators on the approved-sources panel are rendered as `.nsn-detail-source-chip` pills with `--resolved` / `--unresolved` modifiers. Both states pull their colors from Bootstrap 5.3's subtle palette in `spacelab.min.css` — `--bs-success-bg-subtle` / `--bs-success-text-emphasis` / `--bs-success-border-subtle` for resolved, `--bs-secondary-bg-subtle` / `--bs-secondary-color` / `--bs-secondary-border-subtle` for unresolved. **The chip color tokens are not duplicated into `theme-vars.css`** — relying on Bootstrap's subtle system means dark mode flips correctly under `[data-bs-theme="dark"]` without any per-mode rules. If you add a new resolution-state (e.g., "stale" or "needs review"), follow the same pattern: pick a Bootstrap subtle bucket (`info`, `warning`, `danger`) and create a new `--<bucket>` modifier; do not introduce custom hex values for the chip palette.

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

- **Circular import risk:** `products.models` imports `suppliers.models.Supplier`. Any attempt to import `contracts` models from `products` at module top-level would likely create a circular import chain (`products → contracts → products`). `NsnDetailView` already needs `contracts.models.Clin` and `contracts.models.IdiqContractDetails`; it imports them lazily inside `get_context_data`. Follow the same pattern for any new view in this app that needs `contracts` models.

- **`nsn_packout_update` does not use a Django form — validation is inline.** Adding a new packout field requires updating the validation block in `products/views.py` (the `_DECIMAL_FIELDS` tuple for numeric fields, or the `packaging_notes` branch for string fields) AND the `fields`/`widgets` in `contracts/forms.py` `NsnForm`. Forgetting either side leaves the field savable in one path but silently dropped in the other.

- **`ApprovedSource.nsn` is a string field, not an FK to `Nsn`.** NSN codes that appear in `ApprovedSource` may not exist in `Nsn`. NSN codes in `Nsn` may have zero matches in `ApprovedSource`. Both are normal states. The detail page renders an empty-state message when there are no matches; do not treat zero matches as an error condition.

- **`ApprovedSource.approved_cage` is a string field, not an FK to `Supplier`.** CAGE codes that don't resolve to a `Supplier` row are normal — the template renders them with a "not in supplier database" indicator. Do not filter unresolved rows out of the panel; the data-quality signal is intentional.

- **CAGE-to-Supplier resolution in `NsnDetailView.get_approved_sources_data` uses a single batched query** (`Supplier.objects.filter(cage_code__in=cage_set)`) producing a `{cage: supplier}` dict. Do NOT refactor this into per-row queries — at scale (an NSN with 50 approved sources) that becomes a 50-query page load that bypasses the existing `select_related` optimisations elsewhere on the page.

- **`SupplierNSNCapability` is deprecated in practice as of 2026-04-26.** It is no longer surfaced anywhere in the v1 NSN detail UI. Do NOT add new code that reads from it. Do NOT delete the model or its admin registration without a migration plan — the through-table is still wired into `Nsn.suppliers` (M2M `through=`), so removal is a coordinated schema change.

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
| App character | Mostly domain infrastructure. Now also owns `NsnDetailView` and the `nsn_packout_update` JSON endpoint, plus the packout fields on `Nsn`. NSN editing/searching still lives in `contracts/views`. |


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
