# Products Context

## 1. Purpose
The `products` app owns the canonical National Stock Number (NSN) catalog that the contracts/IDIQ flows rely on. It stores each NSN’s descriptive fields, part/reference information, and the supplier capabilities tied to those NSNs. By centralizing this data (with audit metadata), it allows `contracts` views, forms, and APIs to look up, edit, and re-use NSNs across CLINs, IDIQ contract details, and supplier searches.

## 2. App Identity
- **Django app name:** `products` (urls are namespaced under `products`).
- **AppConfig class:** `ProductsConfig` in `products/apps.py`, standard name/auto-field settings.
- **Filesystem path:** `products/` inside the project root.
- **Role:** Support/domain app that exposes the NSN domain objects for the contracts/suppliers ecosystem; it does not ship its own business views but wires into contracts for editing/search.

## 3. High-Level Responsibilities
- Define the audited NSN domain (`Nsn`) and its join table (`SupplierNSNCapability`) linking NSNs to suppliers.
- Keep the database schema compatible with legacy tables (`db_table='contracts_nsn'` and `supplier_nsn_capability`).
- Supply the admin configuration for staff to search and edit NSNs and capability rows.
- Provide the template used by the contracts `NsnUpdateView` (`templates/products/nsn_edit.html`) and the URL namespace for editing/search endpoints that forward to `contracts.views`.
- Serve as the definitive code location for anything that touches NSN metadata so other apps can import `Nsn` and `SupplierNSNCapability` without circular imports.

## 4. Key Files and What They Do
- `apps.py` – Defines `ProductsConfig` so Django can load the app, and the `name = 'products'` label that other apps import.
- `models.py` – Contains `AuditModel`, `Nsn`, and `SupplierNSNCapability`. `AuditModel` adds `created_by`, `created_on`, `modified_by`, `modified_on` and a `save()` override. `Nsn` defines the descriptive fields, the `suppliers` ManyToMany via `SupplierNSNCapability`, and forces the existing `contracts_nsn` table name. `SupplierNSNCapability` stores lead times/prices between a supplier and an NSN.
- `urls.py` – Namespaces the app as `products` and maps `/nsn/<pk>/edit/` and `/nsn/search/` to `contracts.views.NsnUpdateView` and `contracts.views.NsnSearchView`, exposing those flows under `/products/`.
- `admin.py` – Registers `Nsn` and `SupplierNSNCapability` with useful `list_display`/`search_fields` so staff can find records quickly.
- `templates/products/nsn_edit.html` – Extends `contracts/contract_base.html`, renders the `NsnForm` sections (NSN info, description, notes), and re-uses `contracts/includes/simple_field.html` for consistent styling.
- `migrations/0001_initial.py` – Creates the two tables, declares the `contracts_nsn`/`supplier_nsn_capability` names, and wires up the `User` and `Supplier` foreign keys.
- `views.py` – Empty placeholder; the actual UI lives in `contracts.views` but the urls in this app still point there.

## 5. Data Model / Domain Objects
- **`AuditModel` (abstract):** Adds `created_by`/`modified_by` FK to `auth.User`, timestamps with `timezone.now`, and overrides `save()` so `created_on` is set once and `modified_on` always updates just before persisting.
- **`Nsn`:** The core model (stored in `contracts_nsn`). Fields include `nsn_code`, `description`, `part_number`, `revision`, `notes`, `directory_url`, plus the audit fields inherited from `AuditModel`. It exposes `suppliers = ManyToManyField(Supplier, through=SupplierNSNCapability, related_name='capable_nsns')`, so `Supplier` rows can navigate back through `Nsn.suppliers`. The `__str__` prints `NSN {nsn_code}` for admin/search results.
- **`SupplierNSNCapability`:** The `supplier_nsn_capability` table that connects an `Nsn` to a `Supplier` and stores `lead_time_days`/`price_reference`. There are no extra methods, so the table is purely data with the M2M relationship on `Nsn`.

## 6. Request / User Flow
- **Editing an NSN:** `/products/nsn/<int:pk>/edit/` resolves to `contracts.views.NsnUpdateView` (decorated with `conditional_login_required`). The view pulls the `Nsn` instance, renders `contracts/forms.NsnForm` against `templates/products/nsn_edit.html`, flashes a success message, and redirects either back to the owning CLIN (`contracts:clin_detail` when `clin_id` is in the kwargs) or to `contracts:contracts_dashboard`.
- **Searching for NSNs:** `/products/nsn/search/` uses `contracts.views.NsnSearchView` (LoginRequiredMixin). It returns JSON (id/text pairs) for the first ten records whose `nsn_code` or `description` contains the user query, but it refuses to hit the DB until the query string has at least three characters.
- **Contracts select widgets & IDIQ details:** Those JS-driven modals fetch `/contracts/api/options/nsn/` (see `contracts.views.api_views.get_select_options`) or `/contracts/nsn/search/`, so as long as `Nsn` and `SupplierNSNCapability` fields stay consistent, the `clin_form`, `idiq_contract_detail`, and contract detail screens continue to autocomplete NSNs.

## 7. Templates and UI Surface Area
- The single template, `templates/products/nsn_edit.html`, inherits from `contracts/contract_base.html` and renders three sections (NSN info, description, notes) with the shared `contracts/includes/simple_field.html` partials.
- Since the template lives under `templates/products/`, Django loads it whenever `NsnUpdateView` sets `template_name = 'products/nsn_edit.html'`, but the form layout still depends on `contracts/includes/simple_field.html` and the contracts styling system.

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
- `contracts.models.Clin` and `contracts.models.IdiqContractDetails` both FK to `products.Nsn`, so changing the `Nsn` schema will ripple through the contracts schema and migrations such as `0034`.
- `contracts.views.nsn_views.NsnUpdateView`, `contracts.views.idiq_views.NsnSearchView`, `IdiqContractDetailsCreateView`, `IdiqContractDetailsDeleteView`, and `contracts.views.api_views` all import `Nsn`. The edit/search endpoints exposed here are actually defined in `contracts/views`, so this app must stay in sync with the contracts forms/templates.
- `suppliers.Supplier` is referenced via the `suppliers` ManyToMany and the `SupplierNSNCapability` through table, so supplier deletions or migrations can affect capability rows.
- `STATZWeb.decorators.conditional_login_required` controls whether editing requires authentication, which matters because `/products/nsn/<pk>/edit/` just forwards to the contracts view with that decorator applied.
- Key templates (`clin_detail.html`, `contract_management.html`, `clin_form.html`, `idiq_contract_detail.html`) link to the edit/search endpoints, so their JS (select modals, fetch calls to `/contracts/api/options/nsn/`) relies on this app’s models.

## 12. URL Surface / API Surface
- `/products/nsn/<int:pk>/edit/` (`products:nsn_edit`) → `contracts.views.NsnUpdateView` handles GET rendering and POST updates via `NsnForm`.
- `/products/nsn/search/` (`products:nsn_search`) → `contracts.views.NsnSearchView` returns at most 10 matches in JSON once the query has three or more characters.
No other URLs/ APIs live inside `products`; they are simply shims to the contracts implementation.

## 13. Permissions / Security Considerations
- `NsnUpdateView` wraps the view in `conditional_login_required`, so login is required whenever `settings.REQUIRE_LOGIN` is true. The view does not enforce additional per-object ACLs, so broader authorization must be handled by the caller or by restricting who can reach the URL.
- `NsnSearchView` inherits from `LoginRequiredMixin`, ensuring only authenticated users can request the JSON list. It also enforces `len(query) >= 3` before hitting the database, reducing brute-force exposure.
- No additional decorators, permission classes, or object-level filters exist in `products` itself; any tightening must happen in the `contracts` views this app relies on.

## 14. Background Processing / Scheduled Work
None. There are no Celery tasks, periodic jobs, signals, or management commands in `products`.

## 15. Testing Coverage
`products/tests.py` contains only the placeholder comment, so this app has no dedicated automated tests. All NSN-related coverage comes indirectly from the broader `contracts` test suite.

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
- **Primary models:** `Nsn`, `SupplierNSNCapability`, `AuditModel`.
- **Main URLs:** `/products/nsn/<int:pk>/edit/`, `/products/nsn/search/`.
- **Key template:** `templates/products/nsn_edit.html` (extends `contracts/contract_base.html`).
- **Key dependencies:** `contracts.views.NsnUpdateView`/`NsnSearchView`, `contracts.forms.NsnForm`, `suppliers.Supplier`, `STATZWeb.decorators.conditional_login_required`, `contracts.templates/clin_form.html`/`idiq_contract_detail.html` (where the search/edit links live).
- **Risky files to review first:** `contracts/forms.py`, `contracts/views/nsn_views.py`, `contracts/views/idiq_views.py`, and `contracts/models.py` because they define how this app’s models are surfaced to users.


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode overrides via `body.dark`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
