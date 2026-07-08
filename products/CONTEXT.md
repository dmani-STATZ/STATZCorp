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
- Stats cached 10 minutes (`products:observatory_stats` cache key): total NSNs, NSNs with procurement coverage, total `NsnProcurementHistory` rows (plain unfiltered `NsnProcurementHistory.objects.count()` — verified 2026-07-07; any gap vs physical table row count is data drift), canonical contract count (`contracts.Contract.objects.count()`), distinct approved-source CAGEs.
- Recent activity: up to 10 `DibbsAward` rows with NSN. Ordering uses `-aw_file_date`, `-posted_date`, `-id` (not `award_date`). Dedup on `(award_basic_number, delivery_order_number)` keeps the first row seen in a bounded candidate window (400 most-recent rows by file/posted date) — avoids full-table `Window()` on MSSQL (~30s scan). Plus up to 10 latest modified `Nsn` rows after display-only filtering (see §20).

### NSN Dossier (`/products/nsn/<pk>/`, `products:nsn_detail`)
Panels (lazy-loaded sales/contracts data via `nsn_query_variants`):
1. Identity header — formatted NSN, FSC/NIIN, part/rev, duplicate badge.
2. Logistics — read-only + **Edit logistics** modal → POST `products:nsn_logistics_update`.
3. Approved sources — `ApprovedSource` deduped on `(approved_cage, part_number)`; one batched `Supplier` query; `NoQuoteCAGE` badges; orphan count footer.
4. Contracts — `Clin` + `IdiqContractDetails` FKs to `Nsn`; plus `DibbsAwardMod.matched_contract` linkages (left column, below Approved Sources).
5. Government purchase history (`NsnProcurementHistory`, 25 default, `?history=all`).
6. Our activity — `SupplierQuote` + `DibbsAward`/`DibbsAwardMod`.
7. Demand history — `SolicitationLine` + parent `Solicitation` (25 default, `?demand=all`).
8. Price intelligence chart (Chart.js 4.4.1, vendored static) — procurement, quotes, bids, awards series via `json_script`; dual Y axes (unit price left, contract total right); rendered at the bottom of the dossier below all tabular panels.

### Supplier NSN View (`/products/supplier/<pk>/nsns/`, `products:supplier_nsns`)
Approved on / Quoted us / Won / Manual capabilities (`SupplierNSN`). Without `cage_code`, only quote + manual panels with explanatory note. Paginate at 100 rows per panel.

### Legacy flows (unchanged)
- **Editing an NSN:** `/products/nsn/<int:pk>/edit/` → `contracts.views.NsnUpdateView`.
- **Widget JSON search:** `/products/nsn/search/` → `contracts.views.NsnSearchView` (min 3 chars).

## 7. Templates and UI Surface Area
- Portal templates extend `contracts/contract_base.html` and use the standard site header from `base_template.html` (no custom header/banner overrides). Footer chrome (Contract Menu, Reminders) is inherited unchanged.
- `templates/products/nsn_edit.html` — inherits from `contracts/contract_base.html` and renders three sections (NSN info, description, notes) with the shared `contracts/includes/simple_field.html` partials. Since the template lives under `templates/products/`, Django loads it whenever `NsnUpdateView` sets `template_name = 'products/nsn_edit.html'`, but the form layout still depends on `contracts/includes/simple_field.html` and the contracts styling system.
- `templates/products/nsn_detail.html` — NSN Dossier: identity header (prominent NSN code), logistics modal, approved sources, procurement/activity/contracts/demand panels, price chart at page bottom. Extends `contract_base.html`; uses `.nsn-detail-*` (app-core.css) + `.nsn-portal-*` (products-portal.css). Chart.js 4.4.1 + chartjs-adapter-date-fns 3.0.0 vendored under `static/js/vendor/`.

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
- Automated coverage lives in `products/tests/test_nsn_utils.py` and `products/tests/test_search.py`; schema changes still carry risk in coupled `contracts` code paths.
- **`contracts_nsn` test/seed rows (open data-quality item):** Production reports non-NSN `nsn_code` values (e.g. `M1NAV20000403`) and `modified_on` dates far in the future (e.g. 2099-09-30) surfacing in the Observatory "Recently updated NSNs" panel. Local dev MSSQL (verified 2026-07-07) has **41** total `Nsn` rows and **0** future-dated or implausible codes — the junk appears production-specific, likely from manual/SQL seeding rather than a display bug. **Do not delete rows in a display fix.** The Observatory now filters these at render time via `is_plausible_nsn()` + `modified_on__lte=now`; underlying rows remain for a separate cleanup decision. Re-run `Nsn.objects.filter(modified_on__gt=timezone.now())` and scan non-13-char `nsn_code` values in production to capture exact row count and sample PKs before archival.

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

## 20. Portal defect fixes (2026-07-07)

### Price intelligence chart overflow
- **Symptom:** NSN Dossier Price Intelligence panel showed a large blank rectangle (including NSNs with a single award, e.g. pk 130003).
- **Root cause:** Chart.js `maintainAspectRatio: false` without a bounded canvas inside `.nsn-portal-chart-wrap`, plus single-point time-scale charts rendering an invisible domain.
- **Fix:** `static/css/products-portal.css` — `.nsn-portal-chart-wrap` explicit `height: 400px`, `position: relative`, `overflow: hidden`; child `canvas` set to `width/height: 100%`. `nsn_detail.html` chart script pads the X axis ±45 days when only one date exists.

### CAGE omnibox search
- **Symptom:** Valid 5-character CAGE codes returned zero supplier matches.
- **Root cause:** `Supplier.cage_code__iexact` missed rows stored with trailing whitespace padding; classifier otherwise correct for standard 5-char input.
- **Fix:** `_cage_search_token()` + `_suppliers_matching_cage()` in `products/views.py` — `__iexact` first, then bounded `__istartswith` prefix scan with Python `.strip()` verification (no DB-side trim on indexed columns). SAM-only fallback unchanged.

### Observatory "Recently updated NSNs" data quality (display only)
- **Symptom:** Panel showed implausible `nsn_code` strings and future `modified_on` dates from seed/test rows in `contracts_nsn`.
- **Fix:** `is_plausible_nsn()` in `products/nsn_utils.py` (display filter only). `ObservatoryView._get_recent_nsns()` fetches up to 40 candidates with `modified_on__lte=now`, keeps first 10 passing `is_plausible_nsn`. Does not pad when fewer than 10 remain. Underlying rows untouched.

### Site header obscured by panel section title (2026-07-07)
- **Symptom:** On `/products/` and `/products/nsn/<pk>/`, a red striped bar pinned to the viewport top showed the **last** panel section title on that page (e.g. "RECENTLY UPDATED NSNS", "DEMAND HISTORY") instead of the real site header. `/contracts/` was unaffected.
- **Root cause:** Global `header { position: fixed; top: 0; … }` in `static/css/app-core.css` (site nav chrome) matched **every** `<header>` element, including portal `<header class="nsn-detail-panel__head">` rows. All panel headers stacked at `top: 0` with the same striped nav background; the last one in DOM order painted on top of `#header`.
- **Fix:** Scope site nav chrome to `#header` only (`static/css/app-core.css`). Portal panel headers keep their `.nsn-detail-panel__head` styles unchanged.

### Price intelligence chart blank + panel order (2026-07-07)
- **Symptom:** Chart container rendered but no chart drew; dossier placed Price Intelligence above tabular panels.
- **Root cause (chart):** Chart.js 4.4.1 and chartjs-adapter-date-fns 3.0.0 loaded from `cdnjs.cloudflare.com`. No `django-csp` middleware in this repo, but GCC High / restricted egress can block external `<script>` tags silently — the init script exits when `typeof Chart === 'undefined'`. Vendoring removes the external dependency.
- **Fix (chart):** Pin both libraries under `static/js/vendor/`; load via `{% static %}` + `cache_version` in `nsn_detail.html`.
- **Fix (layout):** Move the Price Intelligence `<section>` to the bottom of `nsn_detail.html`, after Demand History.

## 21. Portal integration and stat fixes (2026-07-07)

### Main navigation
- **NSN Portal** added to the site sidebar (`templates/base_template.html`) after Suppliers, before Reports — links to `products:observatory` (`/products/`). Sidebar list spacing tightened (`space-y-1`, `py-1` on `<li>`) so nine items fit within the prior eight-item vertical footprint; anchor `py-2` preserved for click targets.

### NSN Dossier layout
- **Contracts** panel (CLINs, IDIQ details, DIBBS MOD matches) moved from the right column to the left column, below Approved Sources. Left column order: Logistics → Approved Sources → Contracts. Right column: Government Purchase History → Our Activity → Demand History.

### Price intelligence dual-axis chart
- **Symptom:** Government-paid unit-price line appeared flat near zero when award contract totals (10–40× larger) shared the same Y axis.
- **Fix:** Chart.js `y` (left) — "Unit price ($)" for `govt_paid`, `supplier_quoted`, `we_bid`. `y1` (right) — "Contract total ($)" with `grid.drawOnChartArea: false` for `Awards (other)` and `Awards (we won)`. Per-unit and contract-total series must never share one axis again.

### Observatory "Awards we've won" stat
- **Was:** `DibbsAward` rows flagged via `WeWonAward` / `we_won` (raw DIBBS scrape, unmatched noise).
- **Now:** `contracts.Contract.objects.count()`. Rows in `contracts_contract` are canonical post-award wins created through processing finalization or manual entry — Open, Closed, and Canceled are all real contracts; there is no queue/draft state in this table. Company-wide count (Observatory stats are not company-scoped). DIBBS `we_won` data remains on dossier "Our activity" and Observatory "Recent awards" panels.

### Observatory "With procurement history" stat returning 0
- **Root cause:** Set intersection used raw `NsnProcurementHistory.nsn` strings against `Nsn.nsn_normalized` without normalization. Procurement rows are often hyphenated (`4810-01-124-3692`) while the catalog spine is 13-character bare (`4810011243692`), so the intersection was always empty despite dossier pages matching correctly via `nsn_query_variants()`.
- **Fix:** Normalize both sides with `normalize_nsn()` before intersecting catalog codes with distinct procurement NSN values. Count = distinct catalog NSNs with at least one normalized match in procurement history.


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
