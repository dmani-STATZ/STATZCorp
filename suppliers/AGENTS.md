# AGENTS.md — `suppliers` app
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

Read `suppliers/CONTEXT.md` first. This file adds safe-edit guidance that CONTEXT.md does not cover.

---

## 1. Purpose of This File

Defines how to safely modify the `suppliers` Django app. Every rule here is grounded in the actual repo structure. This file is intended for AI coding agents and developers who need to edit this app without breaking cross-app dependencies.

---

## 2. App Scope

**Owns:**
- `Supplier`, `SupplierType`, `Contact`, `SupplierCertification`, `CertificationType`, `SupplierClassification`, `ClassificationType`, `SupplierDocument`, `OpenRouterModelSetting` models
- Supplier dashboard, per-type lists, and detail/enrichment UI
- OpenRouter-backed AI enrichment pipeline (`views.py`, `openrouter_config.py`)
- Templates and static JS for supplier edit, enrichment, and detail views

**Does not own:**
- Supplier CRUD views — those live in `contracts/views/supplier_views.py` and only reuse `suppliers` templates and models
- `contracts.Address`, `contracts.Contract`, `contracts.Clin`, `contracts.SpecialPaymentTerms` — this app FKs into these but does not define them
- Supplier list/search/autocomplete/create/update URL handlers — these are mounted in `contracts/urls.py` and delegated to `contracts` views via `suppliers/urls.py`

**Role:** Feature/support app. It owns supplier metadata, the AI enrichment pipeline, and the dashboard/detail UI. Core transactional supplier flows live in `contracts`.

---

## 3. Read This Before Editing

### Before changing models
- Read `suppliers/models.py` — all models use `db_table = "contracts_*"` (legacy schema). Any field rename directly impacts the shared `contracts_*` tables.
- Read `contracts/models.py` — `Contract`, `Clin`, and `Address` carry FKs that reference supplier tables.
- Read `contracts/forms.py` — `SupplierForm` lives here and is used by supplier create/edit templates.
- Read `migrations/` — three migrations exist; inspect before adding or altering columns.

### Before changing views
- Read `suppliers/views.py` — note which views lack `LoginRequiredMixin` (`DashboardView`, `SupplierDetailView`, `supplier_search_api`).
- Read `contracts/views/supplier_views.py` — this file calls into `suppliers.models` and renders `suppliers/` templates. View changes here affect the supplier edit/create/toggle flows.

### Before changing templates
- Read `templates/suppliers/supplier_detail.html` — includes `{% url 'contracts:...' %}` tags for contacts, certifications, classifications, and contract management. Also includes `transactions/transaction_modal.html`.
- Read `templates/suppliers/includes/address_picker.html` — used in the edit form; references `contracts:address_create` and `suppliers:supplier_edit`.
- Run a repo-wide grep for `{% url 'suppliers:` before renaming any URL name.

### Before changing URLs
- Grep the full repo for `'suppliers:supplier_detail'`, `'suppliers:supplier_edit'`, `'suppliers:supplier_enrich_page'`, `'suppliers:supplier_dashboard'` — these names are referenced in: `contracts` templates, `reports` templates, `sales` templates, `base_template.html`, and Python view reverse calls in `contracts/views/`.

### Before changing enrichment logic
- Read `suppliers/views.py` (enrichment helpers: `call_openrouter_for_supplier`, `fetch_website_html`, `_normalize_*`), `suppliers/openrouter_config.py`, `templates/suppliers/supplier_enrich.html` (inline JS ~lines 760–860), and `static/suppliers/js/supplier_enrich.js`.
- These four files are tightly coupled; a JSON key change in a view breaks the JS and vice versa.

### Before changing forms
- There is no `suppliers/forms.py` — `contracts.forms.SupplierForm` powers both `supplier_form.html` and `supplier_edit.html`. Any form field addition or removal must be done in `contracts/forms.py`.

---

## 4. Local Architecture / Change Patterns

- **Business logic is in `views.py`** — enrichment helpers, normalization functions, and OpenRouter calls all live in `views.py`. There are no separate `services.py` or `selectors.py` files.
- **`openrouter_config.py`** is a standalone config/serialization module; keep `OpenRouterModelSetting` access through `get_default()` and `get_openrouter_model_info()` rather than direct ORM queries.
- **Templates are not thin** — `supplier_enrich.html` and `supplier_detail.html` contain substantial inline JS and logic. Be especially careful with inline JS in `supplier_enrich.html`.
- **No signals, no Celery tasks** — all processing is synchronous. Enrichment happens in-request.
- **`utils.py`** (`scrape_supplier_site`) is not wired into any view or URL. Treat it as dead code until confirmed otherwise.
- **Admin** is important for staff; `SupplierAdmin` fieldsets group compliance/status fields and are the primary staff management UI for supplier records.

---

## 5. Files That Commonly Need to Change Together

### Supplier model field change
`suppliers/models.py` → `suppliers/migrations/` → `contracts/forms.py` (SupplierForm) → `templates/suppliers/supplier_edit.html` / `supplier_form.html` → `suppliers/admin.py` → any `contracts/views/supplier_views.py` AJAX update endpoint that references the field by name → `SupplierApplyEnrichmentView.ALLOWED_FIELDS` if the field is enrichable

`prime` field: `contracts/forms.py` (ModelChoiceField + clean_prime) ↔ `contracts/views/supplier_views.py` (initial value in get_form)

For `name`, `supplier_type`, `prime`, and `is_packhouse`, the supplier detail page also wires inline edits through the transactions modal (`templates/suppliers/supplier_detail.html` + `window.onTransactionSaved`); those fields are listed in `transactions/signals.py` `TRACKED` and captured in the `Supplier` branch of `store_old_state`.

### Enrichment pipeline change
`suppliers/views.py` (enrichment helpers) ↔ `suppliers/openrouter_config.py` ↔ `templates/suppliers/supplier_enrich.html` (inline JS) ↔ `static/suppliers/js/supplier_enrich.js`

### URL rename
`suppliers/urls.py` → all `{% url 'suppliers:<name>' %}` in `templates/suppliers/`, `contracts/templates/contracts/`, `reports/templates/`, `sales/templates/`, `templates/base_template.html` → Python `reverse('suppliers:<name>')` calls in `contracts/views/supplier_views.py` and `contracts/views/contacts_views.py`

### Adding a new enrichment-appliable field
`SupplierApplyEnrichmentView` allowed fields list in `views.py` → `templates/suppliers/supplier_enrich.html` UI + JS → `static/suppliers/js/supplier_enrich.js` if it handles the new field client-side

### AI model config change
`suppliers/openrouter_config.py` → `GlobalAIModelConfigView` in `views.py` → enrichment page inline JS in `supplier_enrich.html`

---

## 6. Cross-App Dependency Warnings

### This app depends on
- `contracts.models`: `Address`, `Contract`, `Clin`, `SpecialPaymentTerms` — heavily used in views and FKed in models
- `contracts.forms`: `SupplierForm` — powers all supplier create/edit forms rendered from `suppliers` templates
- `contracts.views.supplier_views`: `SupplierListView`, `SupplierCreateView`, `SupplierUpdateView`, `SupplierSearchView`, `supplier_autocomplete` — these are imported and mounted in `suppliers/urls.py`
- `transactions` templates: `supplier_detail.html` includes `transactions/transaction_modal.html`

### Apps that import from `suppliers.models`
| App | What it imports |
|-----|----------------|
| `contracts` | `Supplier`, `SupplierType`, `SupplierCertification`, `SupplierClassification`, `Contact`, `CertificationType`, `ClassificationType` |
| `products` | `Supplier` (FK on product model) |
| `processing` | `Supplier` (matching and processing views) |
| `sales` | `Supplier` (RFQ, solicitation, supplier service views) |
| `transactions` | `Supplier` (signal handlers) |

**Any rename of `Supplier` or its fields requires updating all of the above.**

### URL namespace `suppliers:` used in
- `contracts/templates/contracts/` (multiple templates)
- `reports/templates/reports/admin_dashboard.html`
- `sales/templates/sales/rfq/pending.html`, `sent.html`, `solicitations/detail.html`
- `templates/base_template.html`
- `contracts/views/supplier_views.py`, `contracts/views/contacts_views.py` (Python reverse)

---

## 7. Security / Permissions Rules

- `DashboardView`, `SupplierDetailView`, and `supplier_search_api` have **no `LoginRequiredMixin`** — they rely on project-level middleware. Do not silently add `LoginRequiredMixin` without confirming the intended access policy; conversely, do not remove auth from views that currently have it.
- `GlobalAIModelConfigView.post` enforces `request.user.is_superuser` — never remove this check.
- `SupplierApplyEnrichmentView` restricts updates to a hard-coded `ALLOWED_FIELDS` list. Do not expand it without review; new enrichable fields bypass normal form validation.
- The enrichment views (`SupplierEnrichView`, `SupplierApplyEnrichmentView`, `SupplierEnrichPageView`) all require login — preserve `LoginRequiredMixin` on these.
- `AuditModel.save` stamps `modified_by`/`created_by` — do not bypass `super().save()` in subclass overrides.
- OpenRouter API key and fallback model list come from environment settings. Never commit these to VCS.

---

## 8. Model and Schema Change Rules

- **All models use `db_table = "contracts_*"`** — migrations alter the same physical tables that `contracts` queries. A column rename is a cross-app breaking change.
- Before any field rename on `Supplier`: grep the entire repo for the field name string (Python + templates + JS).
- Before changing FKs on `Supplier` (addresses, contact, special_terms): verify `contracts/forms.py` `SupplierForm`, `contracts/views/supplier_views.py` AJAX update endpoints, and `templates/suppliers/supplier_edit.html`.
- `OpenRouterModelSetting` is a singleton keyed on `key="default"`. Never add a migration that deletes or renames this row. Access it via `get_default()`.
- `SupplierDocument.file` uploads to `supplier-docs/` — confirm storage config before changing the `upload_to` path.
- Adding a field to `Supplier` that should appear in the edit form requires updating `contracts/forms.py` (`SupplierForm`), not `suppliers/` alone.

---

## 9. View / URL / Template Change Rules

- The URL name `supplier_detail` is aliased twice: `<int:pk>/` and `<int:pk>/detail/` both map to `SupplierDetailView`. Do not remove either pattern without checking all reverse calls.
- `suppliers/urls.py` imports four views directly from `contracts.views`: `SupplierListView`, `SupplierSearchView`, `SupplierCreateView`, `SupplierUpdateView`, `supplier_autocomplete`. Changing those view names in `contracts` breaks the `suppliers` URL config.
- `supplier_enrich.html` contains a large inline `<script>` block that POSTs to `apply-enrichment/` and `ai-model/config/`. Changes to the JSON payload shape in `SupplierApplyEnrichmentView` or `GlobalAIModelConfigView` must be mirrored here and in `static/suppliers/js/supplier_enrich.js`.
- `supplier_detail.html` references `{% url 'contracts:contact_list' %}`, `{% url 'contracts:supplier_add_certification' %}`, `{% url 'contracts:supplier_add_classification' %}`, and `{% url 'contracts:contract_management' %}`. Verify these `contracts` URL names exist before deploying template changes.
- `supplier_edit.js` tracks form field changes using DOM selectors tied to `supplier_edit.html` field IDs. If field IDs change in the template, update the JS selectors.

---

## 10. Forms / Serializers / Input Validation Rules

- There is no `suppliers/forms.py`. All form validation for supplier create/edit lives in `contracts/forms.py` (`SupplierForm`).
- `SupplierApplyEnrichmentView` validates field names against a hard-coded allowlist and rejects empty values. This is the only server-side gate on enrichment writes — do not weaken it.
- `GlobalAIModelConfigView.post` requires at least one of `model` or `needs_update` in the POST body. Do not remove this check.
- `SupplierEnrichView` normalizes the `manual_only` query param and only calls OpenRouter when `OPENROUTER_API_KEY` is set — keep this guard.
- Address creation in `SupplierApplyEnrichmentView` creates new `contracts.Address` rows without deduplication. Be aware of this if implementing bulk enrichment.

---

## 11. Background Tasks / Signals / Automation Rules

- **No Celery tasks, no cron jobs, no Django signals defined in this app.**
- `transactions/signals.py` imports `Supplier` — changes to `Supplier` may affect signal handlers defined outside this app. Check `transactions/signals.py` before renaming or removing `Supplier` fields.
- All OpenRouter calls are synchronous in-request — timeouts in `fetch_website_html` (default 10s) block the HTTP response.
- `utils.scrape_supplier_site` is not wired to any view or URL. It runs only when manually invoked.

---

## 12. Testing and Verification Expectations

- `suppliers/tests.py` is an empty stub — **zero automated coverage exists in this app.**
- After model changes: verify Django admin loads for `Supplier` and `Contact`, check that `contracts` supplier views (create, edit, list) function, run any existing `contracts` tests.
- After enrichment pipeline changes: manually trigger enrichment for a known supplier via `/suppliers/<pk>/enrich/run/`, confirm the JSON response shape, verify the apply flow POSTs and saves correctly.
- After URL changes: spot-check `contracts` templates that reverse `suppliers:` URLs (contract management page, contact detail page) and the `reports/admin_dashboard.html`.
- After template changes to `supplier_detail.html`: open a supplier detail page with contacts, certifications, classifications, and documents present.
- After changes to `openrouter_config.py`: GET `/suppliers/ai-model/config/` and verify the response fields match what `supplier_enrich.html` JS expects.

---

## 13. Known Footguns

1. **`db_table = "contracts_*"` on every model** — a migration here alters tables that `contracts` also reads. Never assume a migration is isolated to `suppliers`.
2. **No `LoginRequiredMixin` on `DashboardView` and `SupplierDetailView`** — adding it without understanding project-level auth middleware may break publicly accessible or middleware-guarded routes.
3. **`suppliers/urls.py` imports from `contracts.views`** — if `contracts` view class names change, `suppliers/urls.py` breaks at startup.
4. **Inline JS in `supplier_enrich.html`** — this JS block is substantial and directly coupled to view response shapes. It is easy to miss when updating only `views.py`.
5. **`SupplierApplyEnrichmentView` creates `Address` rows without deduplication** — repeated enrichment runs on the same supplier may accumulate near-duplicate address records. The supplier detail page add-address modal avoids duplicate `Address` rows when assigning one new address to multiple slots by POSTing line fields once to `contracts:supplier_update_address`, then chaining follow-up posts with `address_id` only (no line fields) for each additional slot.
6. **`OpenRouterModelSetting` singleton** — direct ORM delete or bulk_create operations can destroy the singleton. Always use `get_default()`.
7. **`contracts/forms.py` owns `SupplierForm`** — adding a field to `Supplier` and forgetting to update `SupplierForm` will silently drop that field from the edit UI.
8. **`supplier_detail` URL has two names** (`supplier_detail` and `supplier_detail_page`) pointing to the same view. Reversals using either name exist in the codebase — removing one breaks callers of that name.
9. **`utils.scrape_supplier_site` prints debug output** — if wired into a view, it will leak crawl logs to stdout in production.
10. **`transactions` signals depend on `Supplier`** — renaming or removing `Supplier` fields without checking `transactions/signals.py` can silently break transaction processing.
11. **`Supplier.prime` is an IntegerField storing a `SalesClass.id`** — it is rendered in `SupplierForm` as a `ModelChoiceField` with a `clean_prime` override that converts the selected instance back to an integer on save. There is no FK constraint at the database level. Do not change this to a real FK without a coordinated migration.

---

## 14. Safe Change Workflow

1. Read `suppliers/CONTEXT.md`, then this file.
2. Read the specific files involved in the change (model, view, template, JS).
3. Grep the full repo for field names, URL names, and import paths before renaming anything.
4. Make the minimal scoped change in `suppliers/`.
5. Update all coupled files identified in Section 5.
6. Check `contracts/forms.py`, `contracts/views/supplier_views.py`, and all templates using `suppliers:` URL names.
7. Verify the Django admin loads, the supplier detail page renders, and the enrichment flow responds correctly.
8. For enrichment changes: confirm JSON payload keys match between `views.py`, `supplier_enrich.html` inline JS, and `supplier_enrich.js`.
9. For model changes: generate and review the migration diff; confirm it only touches `contracts_*` tables that are safe to alter.

---

## 15. Quick Reference

**Primary files to inspect first:**
- `suppliers/models.py`
- `suppliers/views.py`
- `suppliers/urls.py`
- `suppliers/openrouter_config.py`
- `contracts/forms.py` (SupplierForm)
- `contracts/views/supplier_views.py`

**Main coupled areas:**
- Enrichment: `views.py` ↔ `openrouter_config.py` ↔ `supplier_enrich.html` ↔ `supplier_enrich.js`
- Edit form: `contracts/forms.py` ↔ `supplier_edit.html` / `supplier_form.html` ↔ `supplier_edit.js`
- Detail page: `supplier_detail.html` ↔ `SupplierDetailView` ↔ `contracts:` URL names

**Main cross-app dependencies:**
- `contracts` (models, forms, views — bidirectional)
- `products`, `processing`, `sales`, `transactions` (import `Supplier`)
- `reports`, `sales` templates (reverse `suppliers:` URLs)

**Security-sensitive areas:**
- `GlobalAIModelConfigView.post` — superuser check
- `SupplierApplyEnrichmentView` — `ALLOWED_FIELDS` gate
- `LoginRequiredMixin` on enrichment views
- Missing login on `DashboardView` / `SupplierDetailView` (intentional or oversight — do not change without confirming)

**Riskiest edit types:**
- Renaming any `Supplier` field (impacts 6+ apps)
- Renaming `suppliers:` URL names (impacts templates across 4+ apps)
- Changing enrichment JSON payload keys (breaks inline JS)
- Modifying `OpenRouterModelSetting` migrations (singleton risk)
- Adding fields to `Supplier` without updating `contracts/forms.py`


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
