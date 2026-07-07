# Products Context

## 1. Purpose
The `products` app owns the canonical National Stock Number (NSN) catalog (`contracts_nsn`) and the **NSN Portal** — a read-focused research surface that aggregates DIBBS/sales intelligence, supplier data, and contract linkages around each NSN. Contracts/IDIQ flows still use `Nsn` as the FK spine; the portal adds cross-app joins via `nsn_normalized` and `nsn_query_variants()`.

## 2. App Identity
- **Django app name:** `products` (urls are namespaced under `products`).
- **AppConfig class:** `ProductsConfig` in `products/apps.py`, standard name/auto-field settings.
- **Filesystem path:** `products/` inside the project root.
- **Role:** NSN domain owner plus the NSN Portal (Observatory, Dossier, Supplier NSN View). Still wires legacy edit/search JSON endpoints into `contracts.views`.

## 3. High-Level Responsibilities
- Define the audited NSN domain (`Nsn`) with `nsn_normalized` spine (migration `0003`/`0004`) and legacy join table `SupplierNSNCapability` (unused by portal — **do not read**).
- Host the **NSN Portal** three surfaces (all `@login_required`):
  1. **Observatory** — `/products/` — omnibox search, cached portfolio stats, recent awards/NSN activity.
  2. **NSN Dossier** — `/products/nsn/<pk>/` — full intelligence panels + bounded logistics edit.
  3. **Supplier NSN View** — `/products/supplier/<pk>/nsns/` — approved/quoted/won/manual NSNs per supplier.
- Cross-app reads use lazy imports inside view methods; sales NSN string columns are filtered with `nsn_query_variants()` (never DB-side string transforms on indexed columns).
- **Single write path:** logistics fields via `NsnLogisticsForm` POST to `products:nsn_logistics_update` (modal on dossier). Full NSN identity edits remain at `products:nsn_edit` → `contracts.NsnUpdateView`.
- Admin, migrations, `backfill_nsn_normalized` management command, and `products/nsn_utils.py`.

## 4. Key Files and What They Do
- `apps.py` – Defines `ProductsConfig` so Django can load the app, and the `name = 'products'` label that other apps import.
- `models.py` – Contains `AuditModel`, `Nsn`, and `SupplierNSNCapability`. `AuditModel` adds `created_by`, `created_on`, `modified_by`, `modified_on` and a `save()` override. `Nsn` defines the descriptive fields, the `suppliers` ManyToMany via `SupplierNSNCapability`, and forces the existing `contracts_nsn` table name. `SupplierNSNCapability` stores lead times/prices between a supplier and an NSN.
- `nsn_utils.py` – `normalize_nsn`, `format_nsn`, `nsn_query_variants`, `fsc_of`, `niin_of`; mandatory join helper for sales string NSN columns.
- `templatetags/nsn_filters.py` – `|format_nsn` template filter for portal display (wraps `format_nsn()`; display-only).
- `forms.py` – `NsnLogisticsForm` (portal sole write path for weight/dims/packaging notes).
- `views.py` – `ObservatoryView`, `portal_search`, `NsnDetailView`, `nsn_logistics_update`, `SupplierNsnView`.
- `management/commands/backfill_nsn_normalized.py` – idempotent recovery after raw SQL MERGE into `contracts_nsn`.
- `urls.py` – Portal routes plus shims to `contracts.views.NsnUpdateView` / `NsnSearchView`.
- `admin.py` – Registers `Nsn` and `SupplierNSNCapability` with useful `list_display`/`search_fields` so staff can find records quickly.
- `templates/products/nsn_edit.html` – Extends `contracts/contract_base.html`, renders the `NsnForm` sections (NSN info, description, notes), and re-uses `contracts/includes/simple_field.html` for consistent styling.
- `migrations/0001_initial.py` – Creates the two tables, declares the `contracts_nsn`/`supplier_nsn_capability` names, and wires up the `User` and `Supplier` foreign keys.
- `views.py` – Portal views (see §6). Legacy JSON autocomplete remains in `contracts.views.NsnSearchView`.

## 5. Data Model / Domain Objects
- **`AuditModel` (abstract):** Adds `created_by`/`modified_by` FK to `auth.User`, timestamps with `timezone.now`, and overrides `save()` so `created_on` is set once and `modified_on` always updates just before persisting.
- **`Nsn`:** Core model (`contracts_nsn`). Includes `nsn_normalized` (CharField max 13, `blank=True`, `default=""`, `db_index=True`, populated in `save()` via `normalize_nsn(nsn_code)`). **No uniqueness constraint on `nsn_code`** — duplicates possible; dossier shows a data-quality badge linking to admin when `duplicate_count > 1`. Packout/logistics fields: `unit_weight`, `unit_length`, `unit_width`, `unit_height`, `packaging_notes`. M2M `suppliers` through `SupplierNSNCapability` exists in schema only — portal must not read it.
- **`SupplierNSNCapability`:** The `supplier_nsn_capability` table that connects an `Nsn` to a `Supplier` and stores `lead_time_days`/`price_reference`. There are no extra methods, so the table is purely data with the M2M relationship on `Nsn`.

  **Deprecated in practice (as of 2026-04-26):** `SupplierNSNCapability` is not surfaced anywhere in the v1 NSN detail UI. The active source of truth for "which suppliers can supply this NSN" is `sales.ApprovedSource` — a daily DLA-published feed keyed by NSN code (string) and CAGE code (string), surfaced on the NSN detail page via `NsnDetailView.get_approved_sources_data`. `SupplierNSNCapability` is retained in the schema for backward compatibility, still registered in admin, and still wired through `Nsn.suppliers` (M2M `through=`), but it has no documented creation flow and no production data. Do not write new code that reads from it; do not delete it without a migration plan.

## 6. Request / User Flow (NSN Portal)

### Observatory (`/products/`, `products:observatory`)
- Omnibox GET → `/products/search/?q=` (`products:portal_search`).
- Classifier: 13-char NSN → redirect to dossier if one canonical match; 9-digit NIIN → NSN hits; 5-char CAGE → supplier NSN view if one match; else part-number/text search grouped on results page (50 per group).
- Stats cached 10 minutes (`products:observatory_stats` cache key): total NSNs, NSNs with procurement coverage, total `NsnProcurementHistory` rows (plain unfiltered `NsnProcurementHistory.objects.count()` — verified 2026-07-07; any gap vs physical table row count is data drift), we-won awards, distinct approved-source CAGEs.
- Recent activity: up to 10 `DibbsAward` rows with NSN. Ordering uses `-aw_file_date`, `-posted_date`, `-id` (not `award_date`). Dedup on `(award_basic_number, delivery_order_number)` keeps the first row seen in a bounded candidate window (400 most-recent rows by file/posted date) — avoids full-table `Window()` on MSSQL (~30s scan). Plus 10 latest modified `Nsn` rows.

### NSN Dossier (`/products/nsn/<pk>/`, `products:nsn_detail`)
Panels (lazy-loaded sales/contracts data via `nsn_query_variants`):
1. Identity header — formatted NSN, FSC/NIIN, part/rev, duplicate badge.
2. Price intelligence chart (Chart.js 4.4.1) — procurement, quotes, bids, awards series via `json_script`.
3. Logistics — read-only + **Edit logistics** modal → POST `products:nsn_logistics_update`.
4. Government purchase history (`NsnProcurementHistory`, 25 default, `?history=all`).
5. Approved sources — `ApprovedSource` deduped on `(approved_cage, part_number)`; one batched `Supplier` query; `NoQuoteCAGE` badges; orphan count footer.
6. Our activity — `SupplierQuote` + `DibbsAward`/`DibbsAwardMod`.
7. Contracts — `Clin` + `IdiqContractDetails` FKs to `Nsn`; plus `DibbsAwardMod.matched_contract` linkages.
8. Demand history — `SolicitationLine` + parent `Solicitation` (25 default, `?demand=all`).

### Supplier NSN View (`/products/supplier/<pk>/nsns/`, `products:supplier_nsns`)
Approved on / Quoted us / Won / Manual capabilities (`SupplierNSN`). Without `cage_code`, only quote + manual panels with explanatory note. Paginate at 100 rows per panel.

### Legacy flows (unchanged)
- **Editing an NSN:** `/products/nsn/<int:pk>/edit/` → `contracts.views.NsnUpdateView`.
- **Widget JSON search:** `/products/nsn/search/` → `contracts.views.NsnSearchView` (min 3 chars).

## 7. Templates and UI Surface Area
- Portal templates extend `contracts/contract_base.html` and use the standard site header from `base_template.html` (no custom header/banner overrides). Footer chrome (Contract Menu, Reminders) is inherited unchanged.
- `templates/products/nsn_edit.html` — inherits from `contracts/contract_base.html` and renders three sections (NSN info, description, notes) with the shared `contracts/includes/simple_field.html` partials. Since the template lives under `templates/products/`, Django loads it whenever `NsnUpdateView` sets `template_name = 'products/nsn_edit.html'`, but the form layout still depends on `contracts/includes/simple_field.html` and the contracts styling system.
- `templates/products/nsn_detail.html` — NSN Dossier: identity header (prominent NSN code), price chart, logistics modal, approved sources, procurement/activity/contracts/demand panels. Extends `contract_base.html`; uses `.nsn-detail-*` (app-core.css) + `.nsn-portal-*` (products-portal.css). Chart.js 4.4.1 via CDN.

  **Approved Sources panel** (left column, below Packout): renders the `approved_sources` context dict supplied by `NsnDetailView.get_approved_sources_data` as a vertical list of rows, not a table. Each row uses a four-column grid (CAGE / company name / part number / resolution chip) on `≥md` screens and collapses to two lines on smaller screens (CAGE + company on top, part number + chip on bottom). Resolved rows render in normal contrast; unresolved rows get a soft `--bs-tertiary-bg` background and `--bs-secondary-color` text so the eye lands on familiar suppliers first (the view's sort already floats resolved rows to the top — the CSS reinforces that hierarchy). The resolution chip uses Bootstrap 5.3's `--bs-success-bg-subtle` / `--bs-success-text-emphasis` for resolved and `--bs-secondary-bg-subtle` / `--bs-secondary-color` for unresolved; both subtle palettes auto-flip under `[data-bs-theme="dark"]`, so no extra dark-mode rules are needed. Long lists scroll inside the panel via `max-height: 22rem; overflow-y: auto;` on the list. Component classes are prefixed `.nsn-detail-source-*` (live in `static/css/app-core.css`) and follow the same conventions as the rest of the `.nsn-detail-*` family. An orphaned-row footer appears under the list when `approved_sources.orphaned_count > 0` — single italic line, hairline divider above, no alert framing.

## 8. Admin / Staff Functionality
`admin.py` registers both models:
- `NsnAdmin` shows `nsn_code`, `description`, `part_number`, `revision` in the changelist and makes them searchable.
- `SupplierNSNCapabilityAdmin` surfaces the linked NSN/supplier plus `lead_time_days` and `price_reference` so staff can inspect supplier capabilities.
There are no custom inlines or actions; staff use the default Django admin edit form.

## 9. Forms, Validation, and Input Handling
This app does not declare its own forms. The edit flow uses `contracts.forms.NsnForm`, which lists the fields (`nsn_code`, `description`, `part_number`, `revision`, `notes`, `directory_url`), applies consistent CSS/placeholder attributes, and inherits from `BaseModelForm`. All business validation (required fields, uniqueness) lives in the `contracts` form/view layer, so `products` only provides the underlying model definitions.

## 10. Business Logic and Services
Business logic within `products` is limited to:
- `AuditModel.save()` forcing `created_on`/`modified_on` timestamps and leveraging `auth.User` FKs to track editors.
- The ManyToMany configuration between `Nsn` and `Supplier` via `SupplierNSNCapability`, which carries `lead_time_days` and `price_reference` but no custom methods.
All other logic (search throttles, redirect decisions, JSON responses) lives in `contracts.views`. There are no services, selectors, or background jobs defined in this app.

## 11. Integrations and Cross-App Dependencies
- `sales.models.approved_sources.ApprovedSource` is the active source of truth for NSN ↔ supplier relationships in the UI. `products.views.NsnDetailView.get_approved_sources_data` reads it via a lazy import (the `products → sales` direction is the only one that exists; `sales` does not import `products`). `ApprovedSource` joins to `Nsn` by string equality on `nsn` ↔ `nsn_code`, and to `Supplier` by string equality on `approved_cage` ↔ `cage_code`. There are no FKs in either direction.
- `contracts.models.Clin` and `contracts.models.IdiqContractDetails` both FK to `products.Nsn`, so changing the `Nsn` schema will ripple through the contracts schema and migrations such as `0034`.
- `contracts.views.nsn_views.NsnUpdateView`, `contracts.views.idiq_views.NsnSearchView`, `IdiqContractDetailsCreateView`, `IdiqContractDetailsDeleteView`, and `contracts.views.api_views` all import `Nsn`. The edit/search endpoints exposed here are actually defined in `contracts/views`, so this app must stay in sync with the contracts forms/templates.
- `suppliers.Supplier` is referenced via the `suppliers` ManyToMany and the `SupplierNSNCapability` through table, so supplier deletions or migrations can affect capability rows.
- `STATZWeb.decorators.conditional_login_required` controls whether editing requires authentication, which matters because `/products/nsn/<pk>/edit/` just forwards to the contracts view with that decorator applied.
- Key templates (`clin_detail.html`, `contract_management.html`, `clin_form.html`, `idiq_contract_detail.html`) link to the edit/search endpoints, so their JS (select modals, fetch calls to `/contracts/api/options/nsn/`) relies on this app’s models.

## 12. URL Surface / API Surface
- `/products/` (`products:observatory`) → Observatory landing.
- `/products/search/` (`products:portal_search`) → omnibox classifier + results.
- `/products/nsn/<int:pk>/` (`products:nsn_detail`) → NSN Dossier.
- `/products/nsn/<int:pk>/logistics/` (`products:nsn_logistics_update`) → POST logistics form (sole portal write).
- `/products/supplier/<int:pk>/nsns/` (`products:supplier_nsns`) → Supplier NSN View.
- `/products/nsn/<int:pk>/edit/` (`products:nsn_edit`) → `contracts.views.NsnUpdateView`.
- `/products/nsn/search/` (`products:nsn_search`) → `contracts.views.NsnSearchView` (widget JSON).

## 13. Permissions / Security Considerations
- `NsnUpdateView` wraps the view in `conditional_login_required`, so login is required whenever `settings.REQUIRE_LOGIN` is true. The view does not enforce additional per-object ACLs, so broader authorization must be handled by the caller or by restricting who can reach the URL.
- `NsnSearchView` inherits from `LoginRequiredMixin`, ensuring only authenticated users can request the JSON list. It also enforces `len(query) >= 3` before hitting the database, reducing brute-force exposure.
- No additional decorators, permission classes, or object-level filters exist in `products` itself; any tightening must happen in the `contracts` views this app relies on.

## 14. Background Processing / Scheduled Work
None. There are no Celery tasks, periodic jobs, signals, or management commands in `products`.

## 15. Testing Coverage
`products/tests/test_nsn_utils.py` and `products/tests/test_search.py` cover normalization utilities and the omnibox classifier. Run:

```bash
python manage.py test products.tests.test_nsn_utils products.tests.test_search
```

## 16. Migrations / Schema Notes
`0001_initial.py` is the sole migration. It depends on `settings.AUTH_USER_MODEL` and `suppliers.0001_initial`.
- `contracts_nsn` is created with the audit fields, descriptive columns, and is set as the table that `contracts` already expects (`db_table` is hardcoded to keep legacy SQL/views stable).
- `supplier_nsn_capability` holds the `Nsn`/`Supplier` FKs plus optional `lead_time_days` and `price_reference`, and `Nsn.suppliers` is wired to use this through table.
The migration uses `SeparateDatabaseAndState` to avoid touching the existing database state, which is a sign that the table names are intentionally locked.

## 17. Known Gaps / Ambiguities
- `SupplierNSNCapability` is defined but never referenced outside the model/admin; it’s unclear how lead-time/price data is created or maintained today.
- Every view/template for NSN editing/search lives in `contracts`, so renaming a field (e.g., `directory_url`) touches multiple apps, templates, and API responses.
- No tests guard this app, so schema changes carry risk that `contracts` code relies on untested behaviors.
- `products/views.py` is empty, reinforcing that this app is purely a model/URL carrier rather than a self-sufficient feature module.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- Search the `contracts` app for `nsn_code`, `description`, and any `Nsn` references before renaming model fields—the forms, templates (`clin_form.html`, `contract_management.html`, `idiq_contract_detail.html`), and API responses all assume those attributes.
- Changes to `SupplierNSNCapability` affect the `Nsn.suppliers` ManyToMany; coordinate with any supplier maintenance workflow so capability rows do not get orphaned.
- When you touch `templates/products/nsn_edit.html`, simultaneously update `contracts/forms.NsnForm` and ensure `contracts/includes/simple_field.html` still matches the classes/placeholders it expects.
- Any authorization change (e.g., restricting who can edit NSNs) must be made in `contracts.views.nsn_views.NsnUpdateView` because the `products` URLs merely forward to that implementation.
- Because the migration ties the models to legacy tables (`contracts_nsn`, `supplier_nsn_capability`), review raw SQL/management commands that reference those names (e.g., `contracts/management/commands/refresh_nsn_view.py`) before renaming tables or indexes.

## 19. Quick Reference
- **Portal surfaces:** Observatory, NSN Dossier, Supplier NSN View.
- **Join spine:** `Nsn.nsn_normalized` + `nsn_query_variants()` for all sales string NSN columns.
- **Forbidden read:** `SupplierNSNCapability` / `Nsn.suppliers` M2M.
- **Primary models:** `Nsn`, `AuditModel` (`SupplierNSNCapability` schema-only).
- **Main URLs:** `/products/`, `/products/search/`, `/products/nsn/<pk>/`, `/products/supplier/<pk>/nsns/`.
- **Key templates:** `observatory.html`, `nsn_detail.html`, `supplier_nsns.html`, `search_results.html`, `nsn_edit.html`.
- **Key dependencies:** lazy imports of `sales.*`, `contracts.models.Clin`/`IdiqContractDetails`, `suppliers.Supplier`.


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
