# Inventory Context

## 1. Purpose
The `inventory` app owns the warehouse stock ledger described in `inventory/Inventory Application.md`: staff catalog every part by NSN, description, part number, manufacturer, location, quantity, and purchase price, keep it current with adds, edits, deletions, and autocomplete-assisted entry, and work from a server-side dashboard with KPI cards. It also serves a read-only, HMAC-signed JSON API so the public site (`statzcorp-com`) can display items staff have opted in. STATZWeb is the only place inventory is maintained.

## 2. App Identity
- **Django app name:** `inventory` (see `inventory/apps.py`).
- **AppConfig:** `InventoryConfig` (`verbose_name = 'Inventory Management'`).
- **Filesystem path:** `inventory/` under the project root.
- **Classification:** Feature/operational app. UI at `/inventory/`; public API at `/api/inventory/v1/` (both included from `STATZWeb/urls.py`).

## 3. High-Level Responsibilities
- Persist `InventoryItem` (legacy table `STATZ_WAREHOUSE_INVENTORY_TBL`) and recompute `totalcost` on save, null-safe (`inventory/models.py`).
- Shared query logic for the dashboard and the API (`inventory/selectors.py`).
- Server-side dashboard: search, visibility filter, whitelisted sort, pagination, KPI cards, modal delete (`inventory/views.py`, `templates/inventory/dashboard.html`, `static/inventory/js/inventory_dashboard.js`).
- Add/edit/delete views with `InventoryItemForm` plus jQuery UI autocomplete (`forms.py`, `templates/inventory/item_form.html`).
- Read-only public API for `statzcorp-com` (`inventory/api/`, contract in `inventory/INVENTORY_API.md`).
- Register `InventoryItem` in Django admin (`admin.py`).

## 4. Key Files and What They Do
- `models.py`: `InventoryItem` (AutoField `id`, nullable text fields, nullable integer `quantity`, nullable float `purchaseprice`, computed nullable float `totalcost`, `is_public` boolean default `False`). `__str__` returns NSN, else description, else `Inventory item <pk>`.
- `selectors.py`: `build_item_queryset(q, vis, sort, dir)` (dashboard), `public_items_queryset(q, nsn, in_stock)` (API), `inventory_kpis()` (one `aggregate()`), `normalize_sort()`, and the `SORT_FIELDS` whitelist.
- `forms.py`: `BaseFormMixin`/`BaseModelForm` plus `InventoryItemForm`. Explicit `Meta.labels`, `form-control` / `form-check-input` widgets (the mixin's placeholders are stripped), and `clean_quantity` / `clean_purchaseprice` rejecting negatives. No crispy helper.
- `views.py`: dashboard, add/edit/delete, three autocomplete lookups. Every view has `@conditional_login_required`.
- `urls.py`: UI routes under `/inventory/` (URL names unchanged).
- `api/auth.py`: `hmac_required` decorator and `authenticate_request` (supplier-portal signing scheme, inventory secrets).
- `api/serializers.py`: `serialize_public_item` explicit allowlist.
- `api/views.py`: `item_list`, `item_detail` (GET only, CSRF-exempt, `Cache-Control: no-store`).
- `api/urls.py`: `app_name = 'inventory_api'`.
- `templates/inventory/dashboard.html`: Bootstrap 5.3 dashboard (header, KPI cards, GET toolbar, sortable table, pagination, delete modal). No inline JS or CSS.
- `static/inventory/js/inventory_dashboard.js`: search debounce auto-submit (300 ms), select auto-submit, delete modal + `fetch` POST.
- `templates/inventory/item_form.html`: add/edit form. Fields are rendered by name (no loop, no label-string comparisons). Autocomplete URLs are `data-autocomplete-url` attributes. No inline script or style.
- `static/inventory/js/inventory_form.js`: jQuery UI autocomplete (`appendTo` the form) and the live total.
- `templatetags/custom_filters.py`: `custom_currency`.
- `INVENTORY_API.md`: consumer contract for the `statzcorp-com` developer.
- `migrations/`: `0001`–`0004` legacy history; `0005_inventoryitem_is_public` adds `is_public`.

## 5. Data Model / Domain Objects
- **`InventoryItem`** → `STATZ_WAREHOUSE_INVENTORY_TBL`. `nsn`, `description`, `partnumber`, `manufacturer`, `itemlocation` are nullable `CharField`s; `quantity` nullable `IntegerField`; `purchaseprice` nullable `FloatField`; `totalcost` nullable `FloatField`, `editable=False`; `is_public` `BooleanField(default=False)` (column `is_public`, no index).
- `save()` sets `totalcost = purchaseprice * quantity` only when both are non-null; otherwise `totalcost = None`.
- No foreign keys to other apps.

## 6. Request / User Flow
- **Dashboard (`/inventory/`, `/inventory/dashboard`):** query params `q` (searches NSN via `nsn_query_variants` plus `icontains` on description, part number, manufacturer, location), `vis` (`all|public|private`), `sort` (whitelist: `nsn, description, partnumber, manufacturer, itemlocation, quantity, purchaseprice, totalcost, is_public`), `dir` (`asc|desc`), `page`, `per_page` (25/50/100, default 25). Unknown values fall back silently (default order `id`; `id` is always the tiebreaker). Invalid `page` → page 1. Page rows are materialized with `list()` before the KPI aggregate runs.
- **KPIs (whole table):** Total Value (`Sum(quantity * purchaseprice)`), Items, Total Units, Listed Publicly; one `aggregate()`; `None` displays as `0` / `$0.00`.
- **Add / edit (`/inventory/add/`, `/inventory/edit/<pk>/`):** `InventoryItemForm`. Both pass `is_edit`. A valid save sets the "Item saved." message. Add redirects to the dashboard, or back to the add form when `_addanother` was posted. Edit always returns to the dashboard. Negative quantity or unit price is rejected; blank numbers stay null.
- **Delete (`POST /inventory/delete-item/<pk>/`):** returns `{'success': True}`; the dashboard modal posts with `X-CSRFToken` and `credentials: 'same-origin'`, reloads on success, shows an inline alert on failure.
- **Autocomplete:** `/inventory/autocomplete/{nsn,description,manufacturer}/` return up to 10 distinct strings.
- **Public API:** see section 12 and `INVENTORY_API.md`.

## 7. Templates and UI Surface Area
- Both templates extend `base_template.html`, which loads Bootstrap 5.3, Bootstrap Icons, jQuery, and jQuery UI globally.
- `dashboard.html` uses `kpi-tile`/`icon-tile` plus `inv-*` classes in `static/css/app-core.css`. Sort headers and pagination are plain links that preserve all query params. Null cells render `—`. Works in dark mode via Bootstrap/theme variables.
- The dashboard JS is loaded with `?v={{ cache_version }}` (deployment id). The service worker caches nothing, so no SW bump is needed.
- `item_form.html` renders every field by name. Labels come from `Meta.labels`. The page header matches the dashboard (`page-heading`, `btn-outline-brand`). `inv-form-*` rules in `app-core.css` style the sections and the autocomplete menu.

## 8. Admin / Staff Functionality
`admin.site.register(InventoryItem)` with default options. `is_public` is editable there and on the add/edit form.

## 9. Forms, Validation, and Input Handling
- `InventoryItemForm` has no custom `clean()`. Blank quantity/price are allowed and produce `totalcost = None`.
- Dashboard params are validated in the view/selectors (whitelists). API params are validated in `api/views.py`.

## 10. Business Logic and Services
- `selectors.py` holds all list/search/KPI query logic; both the dashboard and the API use it. `nsn_query_variants` is imported lazily inside the selector functions.

## 11. Integrations and Cross-App Dependencies
- `STATZWeb/urls.py` includes `inventory.urls` at `/inventory/` and `inventory.api.urls` at `/api/inventory/v1/` (namespace `inventory_api`).
- `STATZWeb/middleware.py` `LoginRequiredMiddleware.public_urls` contains `/api/inventory/v1/` (prefix match) so signed API calls are not redirected to login.
- `STATZWeb/settings.py`: `INVENTORY_API_KEY`, `INVENTORY_API_HMAC_SECRET` (env vars).
- `products/nsn_utils.py`: `nsn_query_variants()`.
- `STATZWeb/decorators.py`: `conditional_login_required`.
- jQuery UI autocomplete. The JS is loaded by `base_template.html` (CDN); this app does not add a script tag for it. `crispy_forms` is not used by this app.

## 12. URL Surface / API Surface
- `GET /inventory/` and `/inventory/dashboard` — dashboard.
- `GET|POST /inventory/add/`, `GET|POST /inventory/edit/<pk>/`, `POST /inventory/delete-item/<pk>/`.
- `GET /inventory/autocomplete/{nsn,description,manufacturer}/`.
- `GET /api/inventory/v1/items/` — params `q`, `nsn`, `in_stock`, `page`, `page_size` (default 50, max 200). Returns `{count, page, page_size, num_pages, results}`.
- `GET /api/inventory/v1/items/<pk>/` — one public item, else `404 {"error": "not_found"}`.
- API errors: 401 `{"error": {"code": "unauthorized", "message": ...}}`; 400 `{"error": "invalid_parameter"}`; 405 `{"error": "method_not_allowed"}` (after auth).

## 13. Permissions / Security Considerations
- All UI views use `@conditional_login_required`; `LoginRequiredMiddleware` also gates them when `REQUIRE_LOGIN` is on. `inventory` has no `AppRegistry` row, so any logged-in user can open it.
- API auth: `X-API-Key`, `X-Timestamp`, `X-Signature` = hex HMAC-SHA256 of `METHOD\npath\ntimestamp\nbody` (path without query string; GET signs an empty body). ±300 s window. `hmac.compare_digest` throughout. Unset key or secret → 401 (fail closed). Secrets and signatures are never logged.
- API exposes only `id, nsn, description, part_number, manufacturer, quantity` for `is_public=True` rows. No CORS headers; `Cache-Control: no-store` on every response.

## 14. Background Processing / Scheduled Work
None.

## 15. Testing Coverage
`inventory/tests.py` covers: API public-only filtering, key allowlist, null serialization, auth failures (missing/wrong key, bad signature, stale timestamp → identical 401), fail-closed secrets, 405, 404, page-size clamp / invalid params, `q`/`nsn`/`in_stock` filters, middleware behaviour with `REQUIRE_LOGIN=True` (dashboard + autocomplete redirect, API returns 401), dashboard KPIs / sort fallback / invalid page / visibility filter / param-preserving sort links, null-safe `save()`, `__str__`, the form saving `is_public`, non-negative quantity and price, add vs "Save & add another" redirects, prefilled edit values, and no inline script in the form content.

## 16. Migrations / Schema Notes
- `0001`–`0004` legacy history; `0005_inventoryitem_is_public` is AddField only. Existing rows become `is_public=False`.
- `purchaseprice`/`totalcost` stay `FloatField`; legacy nullable columns stay as-is.

## 17. Known Gaps / Ambiguities
- `purchaseprice`/`totalcost` are floats, so money can carry float rounding; changing to `Decimal` is a schema change on a legacy table.
- `purchaseprice` and `quantity` are still floats/ints, so the live total is display-only and can differ from a stored `totalcost` by float rounding.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- Put new list/search logic in `selectors.py` so the dashboard and API stay consistent.
- Never add price, cost, or location to the API serializer or to `public_items_queryset` search.
- When adding a sortable dashboard column, add it to `SORT_FIELDS` and `DASHBOARD_COLUMNS` (in `views.py`) and add the matching `<td>` in `dashboard.html`.
- `base_template.html` links to `inventory:dashboard` twice; keep the URL name.

## 19. Quick Reference
- **Model:** `InventoryItem` (`inventory/models.py`).
- **Selectors:** `inventory/selectors.py`.
- **API:** `inventory/api/` → `/api/inventory/v1/`; contract `inventory/INVENTORY_API.md`.
- **Secrets:** `INVENTORY_API_KEY`, `INVENTORY_API_HMAC_SECRET`.
- **Templates/JS:** `dashboard.html`, `item_form.html`, `static/inventory/js/inventory_dashboard.js`, `static/inventory/js/inventory_form.js`.


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here. Inventory dashboard classes are prefixed `inv-`.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
