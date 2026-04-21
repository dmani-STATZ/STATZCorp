# suppliers Context

## 1. Purpose
Hosts the supplier domain model plus the dashboards/enrichment UI that sits on top of the shared contracts data. This app exposes the supplier dashboard, per-type lists, and detail/enrichment pages that aggregate `Contract`/`Clin` metrics (see `views.py`) and surface AI suggestions, while `contracts.views.supplier_views` re-uses the `suppliers` templates for the CRUD flows.

## 2. App Identity
- Django app name: `suppliers`, configured by `SuppliersConfig` in `suppliers/apps.py`.
- Filesystem path: `suppliers/` inside the project root.
- Registry: included in `STATZWeb/settings.py`'s `INSTALLED_APPS` and mounted at `path("suppliers/", include("suppliers.urls"))` in `STATZWeb/urls.py`.
- Role: a feature/support app that owns supplier metadata, dashboards, AI enrichment, and helper assets rather than the core contract CRUD (that lives in `contracts`).

## 3. High-Level Responsibilities
- Define supplier-related domain objects (`Supplier`, `Contact`, `SupplierDocument`, certifications/classifications, and OpenRouter model settings) that reference `contracts.Address`, `Contract`, `Clin`, and `SpecialPaymentTerms`.
- Drive the supplier dashboard and type-by-type count pages that aggregate `Contract`/`Clin` data, identify top manufacturers/distributors, and expose quick search/autocomplete data.
- Render the supplier detail report that shows contacts, docs, certifications, classifications, contracts, and status flags.
- Implement the OpenRouter-backed enrichment pipeline (fetch HTML, build prompts, normalize JSON, and apply approved values) plus the global AI model configuration endpoint.
- Provide scraper/address/contact normalization helpers for enrichment flows (`_parse_address_text`, `_normalize_*`, `utils.scrape_supplier_site`) and UI wiring.

## 4. Key Files and What They Do

| File | Role |
| --- | --- |
| `models.py` | Defines `AuditModel`, `Supplier` (with contract-related fields, status flags, GSI choices, address FKs), `SupplierType`, `Contact`, certifications/classifications/documents, and `OpenRouterModelSetting` with the shared `key`/`needs_update` flag. Many tables map to existing `contracts` schema via `db_table`. |
| `views.py` | Hosts `DashboardView`, `SupplierDetailView`, `SuppliersInfoByType`, the AI enrichment views (`SupplierEnrichView`, `SupplierApplyEnrichmentView`, `SupplierEnrichPageView`, `GlobalAIModelConfigView`), the `supplier_search_api`, and the helper functions that fetch HTML, query OpenRouter, and normalize addresses/contacts. |
| `urls.py` | Declares the `suppliers` namespace routes (dashboard, detail, info-by-type, search/autocomplete, create/edit aliases, enrichment/run/apply, AI model config). |
| `openrouter_config.py` | Serializes `OpenRouterModelSetting`, falls back to environment defaults, and exposes `get_model_for_request` plus `save_openrouter_model_config`. |
| `utils.py` | Contains the older BeautifulSoup/requests-based `scrape_supplier_site` helper, along with regex constants for phone/email/address/CAGE detection used by enrichment experiments. |
| `admin.py` | Registers `Supplier` and `Contact` with tailored `list_display`, search, filters, and grouped `fieldsets` for compliance metadata. |
| `templates/suppliers/...` | Server-rendered templates for the dashboard, detail page, info-by-type page, enrichment console, edit form (for `contracts` views), list/search screens, and include partials (`address_picker`, `toggle_switch`). |
| `static/suppliers/js` | `supplier_edit.js` (change-tracking/highlight helpers for the edit form) and `supplier_enrich.js` (AJAX apply-suggestion bindings) that are bundled into the templates. |
| `migrations/` | Three migrations: `0001_initial` bootstraps the tables with `contracts_*` naming, `0002` adds enrichment-related fields, and `0003` creates `OpenRouterModelSetting`. |
| `tests.py` | Placeholder file with no tests yet. |

## 5. Data Model / Domain Objects
`AuditModel` supplies `created_by`, `modified_by`, `created_on`, `modified_on`, and a `save` override so derived models automatically timestamp updates.

`Supplier` maps to `contracts_supplier` and centralizes the supplier metadata: name, `cage_code`, `dodaac`, phone/email/web, status flags (`probation`, `conditional`, `archived` plus tracking fields), optional `special_terms`, `prime`, certifications (`ppi`, `iso`), `allows_gsi` choices, references to three `contracts.Address` rows (billing/shipping/physical), a `Contact` FK for the primary contact, optional `packhouse` self-reference, `logo_url`, `last_enriched_at`, and the `files_url`/`notes` fields that drive detail templates.

`SupplierType`, `CertificationType`, and `ClassificationType` are lookups persisted as `contracts_suppliertype`, `contracts_certificationtype`, and `contracts_classificationtype`. `Supplier` links to `SupplierType`, and the certification/classification models point back to `Supplier` plus the respective type table; each has `__str__` helpers for UI labels.

`Contact` holds the name/title/company/phone/email for a supplier, optionally linked to a `contracts.Address` and back to `Supplier` via `contacts`.

`SupplierDocument` extends `AuditModel` to store uploaded files (upload path `supplier-docs/`), document `doc_type` (CERT/CLASS/GENERAL), optional links to the associated certification/classification, and a `description`; `SupplierDetailView` selects the latest 25 docs and matches them to certifications/classifications.

`OpenRouterModelSetting` keeps the shared AI model metadata (`key`, `model_name`, `needs_update`, timestamps, `updated_by`). `openrouter_config.get_default()` always returns the `key="default"` row, `get_model_for_request` chooses stored vs. fallback vs. hard-coded default (`mistralai/mistral-small:free`), and `save_openrouter_model_config` tracks who made the change.

## 6. Request / User Flow
1. **Dashboard (`/suppliers/` & `/suppliers/dashboard/`)** – `DashboardView` collects supplier/contract counts, top suppliers by contract count/value, type counts, and recently active suppliers (via `Contract`/`Clin`) while the template issues AJAX queries against `supplier_search_api` for the live search box.
2. **Supplier detail (`/suppliers/<pk>/detail/`)** – `SupplierDetailView` populates contacts, documents, certifications/classifications, contract aggregates, and compliance flags. The template renders status toggles, a document list, and contract/company summaries; it also renders the `supplier_enrich.html` link/button once the user navigates to enrichment. **`name`, `supplier_type`, `prime`, and `is_packhouse` are inline-editable on the detail page via the transactions modal** (click-to-edit spans that POST through `transactions` and refresh in place). Contacts can be added, edited, and deleted inline via a modal in the Contacts section (POST to `contracts:supplier_save_contact` / `contracts:supplier_delete_contact`) without leaving the page. New addresses can be created and assigned to billing, shipping, and physical slots inline via the Add New Address modal (POST to `contracts:supplier_update_address`), including assigning one new row to multiple slots in a single save flow.
3. **AI enrichment (`/suppliers/<pk>/enrich/run/`, `/suppliers/<pk>/enrich/`, `/suppliers/<pk>/apply-enrichment/`)** – `SupplierEnrichPageView` builds the snapshot/context (including `global_ai_model_info`), `SupplierEnrichView` fetches the supplier website (`fetch_website_html`), calls OpenRouter (`call_openrouter_for_supplier`), sanitizes/normalizes the JSON, and returns suggestions; `SupplierApplyEnrichmentView` accepts JSON (allowed fields plus address types) and persists only the safe fields while flagging `last_enriched_at` and `modified_by`.
4. **Global AI model config (`/suppliers/ai-model/config/`)** – `GlobalAIModelConfigView` exposes the stored model/fallback info via GET and lets superusers set `model_name` or `needs_update` via POST. The enrichment page wires this endpoint into its inline JS.
5. **List/create/edit/search (via `contracts.views.supplier_views`)** – `contracts` exposes `SupplierListView`, `SupplierSearchView`, `SupplierCreateView` (`suppliers/supplier_form.html`), and `SupplierUpdateView` (`suppliers/supplier_edit.html`) plus quick update/toggle/certification/classification management endpoints; these views import `suppliers.models` and reuse the templates/static assets defined here.
6. **Helper endpoints** – `supplier_search_api` returns the top 15 matches for dashboard search/autocomplete; `SuppliersInfoByType` serves `/suppliers/info/<type_slug>/` with a paginated list filtered by `supplier_type.description`.

## 7. Templates and UI Surface Area
- `templates/suppliers/dashboard.html` – dashboard cards, supplier-type links, and inline JS that hits `/suppliers/search/` (JSON) to redirect to detail pages.
- `templates/suppliers/supplier_detail.html` – detail layout that loops through `contacts`, `documents`, `certification_rows`, `classification_rows`, and `contracts`; the view also supplies `certification_types`/`classification_types` for dropdowns and `ContentType` IDs for client-side helpers.
- `templates/suppliers/suppliers_by_type.html` – simple ListView template showing 2 suppliers per page plus `type_label` provided by `SuppliersInfoByType`.
- `templates/suppliers/supplier_enrich.html` – enrichment console with manual JSON input, AI/model status block, address picker, and inline script (lines ~760–860) that POSTs to `/suppliers/<pk>/apply-enrichment/` and `/suppliers/ai-model/config/`.
- `templates/suppliers/supplier_edit.html` & `supplier_form.html` – live supplier edit/create forms driven by `contracts.forms.SupplierForm`, using includes like `suppliers/includes/address_picker.html`, `toggle_switch.html`, and `contracts/includes/simple_field.html`; `supplier_edit.js` adds change-tracking visuals.
- `templates/suppliers/supplier_list.html`, `supplier_search.html`, `supplier_search` partials – consumed by the `contracts` supplier views, including a legacy `legacy_supplier_detail.html` that currently has no code path (see Known Gaps).
- `static/suppliers/js` – `supplier_edit.js` tracks field diffs/change badges for the edit form, while `supplier_enrich.js` wires the “apply suggestion” button to `SupplierApplyEnrichmentView` and handles CSRF/feedback for API calls.

## 8. Admin / Staff Functionality
`admin.py` registers `Supplier` with fieldsets grouped into Basic, Contact, Branding, Addresses, Compliance & Status, and Metadata. Admin staff get list filters on `archived` and `supplier_type`, searchable name/CAGE/DODAAC, and a `Contact` admin with company/email/phone search. Staff changes still rely on the `AuditModel` fields if they exist.

## 9. Forms, Validation, and Input Handling
- This app does not define its own Django `forms.py`; `contracts.forms.SupplierForm` powers the create/edit forms rendered by the `suppliers` templates. The `prime` field is rendered as a `ModelChoiceField` over `SalesClass` (ordered by `sales_team`) with a `clean_prime` override that saves the selected instance's integer `id` back to `Supplier.prime`. No FK exists at the schema level.
- `SupplierApplyEnrichmentView` expects JSON payloads with `field`/`value`, restricts updates to a hard-coded list (`logo_url`, `primary_phone`, etc.), and treats the special `"address"` field by creating a new `contracts.Address` then wiring it to the selected shipping/billing/physical slots.
- `SupplierEnrichView` normalizes `manual_only` query params and only calls OpenRouter when an API key is configured; errors (invalid JSON, HTTP failures) become `JsonResponse` errors with appropriate HTTP codes.
- `global_ai_model_config` POST validates that either `model_name` or `needs_update` is supplied and rejects non-superusers with HTTP 403; the GET response drives the enrichment UI’s status block.
- `supplier_search_api` reads `q` and filters `name`, `cage_code`, or `contract__contract_number` to keep the dashboard search fast and stateless.

## 10. Business Logic and Services
- `_parse_address_text`, `_normalize_addresses`, and `_normalize_contact_rows` in `views.py` turn verbose OpenRouter/HTML results into structured data for display/persistence.
- `call_openrouter_for_supplier` builds the system/user prompts (`SUPPLIER_ENRICH_SYSTEM_PROMPT`, HTML snippet trimming to `SUPPLIER_ENRICH_HTML_MAX_CHARS`), composes the request (including optional fallback models from `OPENROUTER_MODEL_FALLBACKS`), handles HTTP errors, and returns the normalized payload plus the model used.
- `fetch_website_html` normalizes URLs, enforces HTTP/HTTPS, and raises `RuntimeError` when requests fail; `normalize` functions are reused by the enrichment view to pre-fill the page before persisting.
- `DashboardView`, `SupplierDetailView`, and `SuppliersInfoByType` compute counts/sums (`Count`, `Sum`, `Coalesce`) over `Supplier`, `Contract`, and `Clin` to show top suppliers and performance flags; `SupplierDetailView` also maps documents to certifications/classifications before rendering.
- `utils.scrape_supplier_site` is a fallback scraper that crawls up to three pages, prints the crawl/debug info, and aggregates phone/email/address/logo/CAGE hints via regex/JSON-LD heuristics—it is not referenced elsewhere but may still be useful for manual data gathering.

## 11. Integrations and Cross-App Dependencies
- Depends on `contracts.models` (`Contract`, `Clin`, `Address`, `SpecialPaymentTerms`) for metrics, address creation, and the `SupplierForm` that drives the edit/create flows defined in `contracts.views.supplier_views`.
- `contracts.views.supplier_views` defines the `SupplierListView`, `SupplierSearchView`, `SupplierCreateView`, `SupplierUpdateView`, and the certification/classification endpoints that import `suppliers.models` and reuse `suppliers/templates` plus `static/suppliers/js`.
- `STATZWeb` provides the Django project scaffolding: `settings.py` registers the app, `urls.py` includes the namespace, and `STATZWeb.decorators.conditional_login_required` guards many `contracts` views that interact with this app’s data.
- External dependencies: `requests` for HTTP GET/POST to supplier websites and OpenRouter, `beautifulsoup4` for the scraper, and environment settings (`OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_HTTP_REFERER`, `OPENROUTER_X_TITLE`, `OPENROUTER_MODEL_FALLBACKS`, `OPENROUTER_MODEL`).
- Auth cross-link: `AuditModel`/`Supplier`/`SupplierDocument` track `User` via `created_by`/`modified_by`, and `OpenRouterModelSetting.updated_by` records who toggles the shared AI model.

## 12. URL Surface / API Surface
- `/suppliers/` & `/suppliers/dashboard/` → `DashboardView`.
- `/suppliers/details/` → delegated supplier list (mirrors `contracts.views.SupplierListView`) and `/suppliers/search/page/` for the AJAX-backed search page.
- `/suppliers/search/` → `supplier_search_api` (JSON) used by the dashboard search box and autocomplete UI.
- `/suppliers/info/<type_slug>/` → `SuppliersInfoByType` with a per-type paginated list.
- `/suppliers/autocomplete/`, `/suppliers/create/`, `/suppliers/<pk>/`, `/suppliers/<pk>/detail/`, `/suppliers/<pk>/enrich/run/`, `/suppliers/<pk>/enrich/`, `/suppliers/<pk>/apply-enrichment/`, `/suppliers/<pk>/edit/`, `/suppliers/ai-model/config/` → detail, enrichment, edits, and model config endpoints defined in `suppliers.urls`.
- Additional `contracts` routes under `contracts/urls.py` expose `/suppliers/` (list), `/supplier/<pk>/` (detail/edit/create), `/supplier/<pk>/toggle-flag/`, `/supplier/<pk>/update-*` (notes, selects, compliance, files, address), `/supplier/<pk>/contact/...`, `/supplier/<pk>/certification/...`, `/supplier/<pk>/classification/...`, `/supplier/search/`, and autocomplete/admin tooling; these call into `contracts.views.supplier_views`.

## 13. Permissions / Security Considerations
- `SupplierEnrichView`, `SupplierApplyEnrichmentView`, `SupplierEnrichPageView`, `SuppliersInfoByType`, and `GlobalAIModelConfigView` require login via `LoginRequiredMixin`; the enrichment POSTs also enforce CSRF and the `apply` view restricts fields to a curated list plus address-types.
- The enrichment pipeline only touches `Supplier` fields that have explicit UI hooks and records `modified_by`/`last_enriched_at`; it also rejects empty `value` submissions for the non-address fields.
- `GlobalAIModelConfigView.post` returns HTTP 403 for non-superusers and expects at least one of `model` or `needs_update` to avoid accidental clears.
- Dashboard/search endpoints (`supplier_search_api`, `DashboardView`) have no explicit mixins, so they inherit whatever global middleware/auth `STATZWeb` applies; upgrade caution is required if you tighten access.
- OpenRouter secrets (API key, referer overrides, fallback model list) come from settings/environment, so keep them out of VCS and review the `requests` calls for sensitive headers.

## 14. Background Processing / Scheduled Work
No Celery/RQ tasks, cron jobs, or scheduled imports live here—the AI enrichment is synchronous (views call OpenRouter directly), and the scraper in `utils.py` currently only runs when invoked manually (it prints logs per crawl but is not wired into a job queue).

## 15. Testing Coverage
`tests.py` is still the auto-generated stub with no assertions, so this app has zero automated coverage; the `contracts` app owns most supplier flows and should ideally test the shared templates/static assets as well.

## 16. Migrations / Schema Notes
- Only three migrations exist: `0001_initial` (creates the `contracts_*` tables and wires FKs to `contracts.Address`, `SpecialPaymentTerms`, and `User`), `0002` (adds `logo_url`, `website_url`, `primary_email`, `primary_phone`, and `last_enriched_at` to `Supplier`), and `0003` (creates `suppliers.OpenRouterModelSetting` with the `needs_update` flag).
- The models deliberately set `db_table` to `contracts_*` to align with the legacy schema, so migrating/renaming fields impacts the shared tables that `contracts` also queries.
- `AuditModel.save` enforces consistent timestamps, and `OpenRouterModelSetting` maintains a single `key="default"` record via `get_or_create`, so manual edits should respect that singleton pattern.

## 17. Known Gaps / Ambiguities
- `tests.py` is empty and no app-level tests exist—coverage lives upstream in `contracts`.
- `templates/suppliers/legacy_supplier_detail.html` and `utils.scrape_supplier_site` are not referenced by any view/URL; confirm whether they are dead code before touching them.
- The enrichment template relies on inline JS (lines 760–860) to POST both field updates and global model config updates; if the JS changes, mirror those updates in `static/suppliers/js` (currently only used for the edit page).
- `SupplierApplyEnrichmentView` creates new `contracts.Address` rows for suggested addresses but does not dedupe; multiple enrichments could rapidly add nearly identical addresses unless upstream cleanup occurs elsewhere.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- Any change to `Supplier` fields (names, addresses, statuses) must consider all `contracts.views.supplier_views` endpoints and templates that expect those names (`supplier_form.html`, `supplier_edit.html`, detail page loops, and the AJAX update endpoints).
- The enrichment workflow couples `views.py`, `openrouter_config.py`, `templates/suppliers/supplier_enrich.html`, and `static/suppliers/js/supplier_enrich.js`; changing one file requires verifying the others for synchrony (e.g., JSON payload keys, button IDs, CSRF usage).
- The AI config row is meant to be a singleton; use `OpenRouterModelSetting.get_default()` instead of direct queries and ensure you do not accidentally delete the default key in migrations.
- Dashboard/Detail metrics run wide joins (`Contract`, `Clin`, `SupplierCertification`, etc.), so heavy filtering tweaks should be re-tested for performance/duplicate counts (the view limits results like documents to 25/`recently_active_suppliers` to keep kernels small).
- Before renaming templates, search for string-based references in `contracts` URLs/views and the `static` JS files, as everything shares the `suppliers/*` template namespace.

## 19. Quick Reference
- Primary models: `Supplier`, `Contact`, `SupplierCertification`, `SupplierClassification`, `SupplierDocument`, `OpenRouterModelSetting`.
- Main URLs: `/suppliers/` (dashboard), `/suppliers/<pk>/detail/`, `/suppliers/<pk>/enrich/` + `/apply-enrichment/`, `/suppliers/info/<type_slug>/`, `/suppliers/search/` & `/autocomplete/`, `/suppliers/ai-model/config/`.
- Key templates: `templates/suppliers/dashboard.html`, `supplier_detail.html`, `supplier_enrich.html`, `supplier_edit.html`/`supplier_form.html`, `suppliers_by_type.html`.
- Key dependencies: `contracts` app for models/forms/views, `STATZWeb` login/URL wiring, external OpenRouter API (`requests` + env vars) and `beautifulsoup4` for `utils`.
- Risky files to review first: `views.py` (AI/enrichment logic), `openrouter_config.py`, `static/suppliers/js/supplier_enrich.js`, `templates/suppliers/supplier_detail.html`, `templates/suppliers/supplier_enrich.html`.


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode overrides via `body.dark`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
