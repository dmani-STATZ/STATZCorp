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
- Two-way spreadsheet sync with Cori's `Inventory_Tracker.xlsx` (`inventory/sync/`, see section 20).
- Register `InventoryItem` and a read-only `InventorySyncRun` in Django admin (`admin.py`).

## 4. Key Files and What They Do
- `models.py`: `InventoryItem` (AutoField `id`, nullable text fields, nullable integer `quantity` and `quantity_remaining`, nullable float `purchaseprice`, computed nullable float `totalcost`, `is_public` boolean default `False`, `last_modified` `auto_now`). Properties `on_hand` / `on_hand_value`. `__str__` returns NSN, else description, else `Inventory item <pk>`. `InventorySyncRun` stores each upload (bytes, plan, errors, warnings, status).
- `sync/`: `parser.py`, `matcher.py`, `apply.py`, `exporter.py`, `banner.py` (section 20).
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
- `templates/inventory/sync_home.html`, `sync_preview.html`, `_sync_banner.html`, `_sync_status.html`: sync UI (no JS).
- `migrations/`: `0001`–`0004` legacy history; `0005_inventoryitem_is_public` adds `is_public`; `0006_inventory_sync` adds `quantity_remaining`, `last_modified`, and `InventorySyncRun`.

## 5. Data Model / Domain Objects
- **`InventoryItem`** → `STATZ_WAREHOUSE_INVENTORY_TBL`. `nsn`, `description`, `partnumber`, `manufacturer`, `itemlocation` are nullable `CharField`s; `quantity` nullable `IntegerField`; `purchaseprice` nullable `FloatField`; `totalcost` nullable `FloatField`, `editable=False`; `is_public` `BooleanField(default=False)` (column `is_public`, no index).
- `quantity_remaining` nullable `IntegerField` (no `db_column`): filled only for bulk lots drawn down over time. `last_modified` `DateTimeField(auto_now=True, null=True)`; legacy rows stay NULL until next save.
- `save()` sets `totalcost = purchaseprice * quantity` only when both are non-null; otherwise `totalcost = None`. `totalcost` matches the spreadsheet's Total Cost column (quantity bought × price), not what is on hand.
- `on_hand` = `quantity_remaining` when not None, else `quantity or 0`. `on_hand_value` = `on_hand * purchaseprice`, or None without a price. On-hand value is the company's inventory value (dashboard KPI, spreadsheet ON-HAND VALUE row).
- **NSN is not unique.** The same NSN appears on several rows (separate lots, different prices); some rows have a blank NSN. Never add a unique constraint on `nsn`.
- **`InventorySyncRun`**: `created_at`, `created_by` (FK user, SET_NULL), `original_filename`, `file_bytes` (the uploaded workbook), `status` (`preview|applied|discarded|failed`), `plan`/`errors`/`warnings` (JSON), `applied_at`. Ordered `-created_at`. Rows are never deleted by code.
- No foreign keys to other apps (only `created_by` → user).

## 6. Request / User Flow
- **Dashboard (`/inventory/`, `/inventory/dashboard`):** query params `q` (searches NSN via `nsn_query_variants` plus `icontains` on description, part number, manufacturer, location), `vis` (`all|public|private`), `sort` (whitelist: `nsn, description, partnumber, manufacturer, itemlocation, quantity, purchaseprice, totalcost, is_public`), `dir` (`asc|desc`), `page`, `per_page` (25/50/100, default 25). Unknown values fall back silently (default order `id`; `id` is always the tiebreaker). Invalid `page` → page 1. Page rows are materialized with `list()` before the KPI aggregate runs. The table has a `Remaining` column after `Qty` (sortable as `quantity_remaining`); the per-row `Total` column is still `totalcost`.
- **KPIs (whole table):** On-Hand Value (`kpis.on_hand_value`: `Sum(Case(When(quantity_remaining not null → quantity_remaining * purchaseprice), default quantity * purchaseprice))`), Items (`item_count`), On-Hand Units (`on_hand_units`, same `Case` without price), Listed Publicly (`public_count`); one `aggregate()`; `None` displays as `0` / `$0.00`.
- **Toolbar:** Sync spreadsheet (`sync_home`), Download spreadsheet (`sync_export`), Add Item.
- **Add / edit (`/inventory/add/`, `/inventory/edit/<pk>/`):** `InventoryItemForm`. The Stock row is Location, Quantity, Qty Remaining (optional, non-negative, help text about bulk lots), Unit Price. The live "Total value" line is still Quantity × Unit Price. Both pass `is_edit`. A valid save sets the "Item saved." message. Add redirects to the dashboard, or back to the add form when `_addanother` was posted. Edit always returns to the dashboard. Negative quantity or unit price is rejected; blank numbers stay null.
- **Delete (`POST /inventory/delete-item/<pk>/`):** returns `{'success': True}`; the dashboard modal posts with `X-CSRFToken` and `credentials: 'same-origin'`, reloads on success, shows an inline alert on failure.
- **Autocomplete:** `/inventory/autocomplete/{nsn,description,manufacturer}/` return up to 10 distinct strings.
- **Public API:** see section 12 and `INVENTORY_API.md`.

## 7. Templates and UI Surface Area
- Both templates extend `base_template.html`, which loads Bootstrap 5.3, Bootstrap Icons, jQuery, and jQuery UI globally.
- `dashboard.html` uses `kpi-tile`/`icon-tile` plus `inv-*` classes in `static/css/app-core.css`. Sort headers and pagination are plain links that preserve all query params. Null cells render `—`. Works in dark mode via Bootstrap/theme variables.
- The dashboard JS is loaded with `?v={{ cache_version }}` (deployment id). The service worker caches nothing, so no SW bump is needed.
- `item_form.html` renders every field by name. Labels come from `Meta.labels`. The page header matches the dashboard (`page-heading`, `btn-outline-brand`). `inv-form-*` rules in `app-core.css` style the sections and the autocomplete menu.

## 8. Admin / Staff Functionality
`admin.site.register(InventoryItem)` with default options. `is_public` is editable there and on the add/edit form. `InventorySyncRun` is registered read-only (no add / change / delete); `file_bytes` is excluded and deferred.

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
- `contracts/utils/excel_utils.py`: lazy openpyxl wrapper (`load_workbook`, `Workbook`, style classes), imported inside `inventory/sync/` functions only.
- `STATZWeb/decorators.py`: `conditional_login_required`.
- jQuery UI autocomplete. The JS is loaded by `base_template.html` (CDN); this app does not add a script tag for it. `crispy_forms` is not used by this app.

## 12. URL Surface / API Surface
- `GET /inventory/` and `/inventory/dashboard` — dashboard.
- `GET|POST /inventory/add/`, `GET|POST /inventory/edit/<pk>/`, `POST /inventory/delete-item/<pk>/`.
- `GET /inventory/autocomplete/{nsn,description,manufacturer}/`.
- Sync: `GET /inventory/sync/` (`sync_home`), `POST /inventory/sync/upload/` (`sync_upload`), `GET /inventory/sync/<run_id>/` (`sync_preview`), `POST /inventory/sync/<run_id>/apply/` (`sync_apply`), `POST /inventory/sync/<run_id>/discard/` (`sync_discard`), `GET /inventory/sync/export/` (`sync_export`).
- `GET /api/inventory/v1/items/` — params `q`, `nsn`, `in_stock`, `page`, `page_size` (default 50, max 200). Returns `{count, page, page_size, num_pages, results}`.
- `GET /api/inventory/v1/items/<pk>/` — one public item, else `404 {"error": "not_found"}`.
- API errors: 401 `{"error": {"code": "unauthorized", "message": ...}}`; 400 `{"error": "invalid_parameter"}`; 405 `{"error": "method_not_allowed"}` (after auth).

## 13. Permissions / Security Considerations
- All UI views use `@conditional_login_required`; `LoginRequiredMiddleware` also gates them when `REQUIRE_LOGIN` is on. `inventory` has no `AppRegistry` row, so any logged-in user can open it.
- API auth: `X-API-Key`, `X-Timestamp`, `X-Signature` = hex HMAC-SHA256 of `METHOD\npath\ntimestamp\nbody` (path without query string; GET signs an empty body). ±300 s window. `hmac.compare_digest` throughout. Unset key or secret → 401 (fail closed). Secrets and signatures are never logged.
- API exposes only `id, nsn, description, part_number, manufacturer, quantity` for `is_public=True` rows. `quantity` is `on_hand`; `in_stock` means on hand > 0; list order is NSN then id with blank NSNs last. `quantity_remaining`, `last_modified`, and `is_public` are never serialized.
- Sync views use `@conditional_login_required`; upload / apply / discard are `@require_POST` with CSRF. Uploaded file contents and row values are never logged. No CORS headers; `Cache-Control: no-store` on every response.

## 14. Background Processing / Scheduled Work
None.

## 15. Testing Coverage
`inventory/tests_sync.py` builds Cori-style workbooks in-test (title row, blank I2, `*housed at Quality Support`, same-NSN lots, blank NSN, blank rows, `TOTAL ` row, `PurchaseOrders` sheet with a formula and yellow fill) and covers: first sync into an empty table, key matching into existing rows, export round trip = no-op with `exported_at` read from J1/K1, edit/delete/add in an exported file, the keep rule (and removal when the file has no stamp), duplicate and unknown STATZ IDs, row errors (negative qty, bad price, uncalculated formula) → failed run, `.xls` / oversize / non-zip rejection, older previews discarded, stale-apply refusal, non-preview refusal, the large-removal checkbox (server-side), `is_public` preserved / new items private, `save()` recomputing `totalcost` / `last_modified`, export layout (hidden J/K, stamp, freeze panes, TOTAL / ON-HAND VALUE formulas, carried sheet), the export view, API `quantity` = on hand / `in_stock` / NSN ordering, the On-Hand Value KPI, the sync banner (shown within 60 days, hidden at 61), sync pages, `quantity_remaining` validation, and anonymous redirect.

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
- **Models:** `InventoryItem`, `InventorySyncRun` (`inventory/models.py`).
- **Sync:** `inventory/sync/`; pages under `/inventory/sync/`.
- **Selectors:** `inventory/selectors.py`.
- **API:** `inventory/api/` → `/api/inventory/v1/`; contract `inventory/INVENTORY_API.md`.
- **Secrets:** `INVENTORY_API_KEY`, `INVENTORY_API_HMAC_SECRET`.
- **Templates/JS:** `dashboard.html`, `item_form.html`, `static/inventory/js/inventory_dashboard.js`, `static/inventory/js/inventory_form.js`.

## 20. Spreadsheet Sync

### Flow
Cori uploads her workbook as-is (`sync_upload`) → `create_run` parses it and saves an `InventorySyncRun` (`preview`, or `failed` with row-numbered errors) and discards every older `preview` → the preview page shows adds / updates / removes / kept / unchanged → **Apply** (`apply_run`) changes the table → **Download updated spreadsheet** (`sync_export`) serves a STATZWeb-built workbook that looks like hers plus hidden `STATZ ID` / `STATZ Version` columns. She works from that file and repeats.

### Master-copy rules
- While Cori uploads, the spreadsheet is the master: on every row the file knows about, its values win (conflicts are flagged, not blocked).
- Editing on the page stays enabled. Items added (or edited) on the page after her file was downloaded are **kept**, not deleted.
- If she stops uploading, the page is the master with no code change; the banner disappears 60 days after the last applied sync.

### Modules (`inventory/sync/`)
| Module | Role |
|---|---|
| `parser.py` | `.xlsx` only, ≤ 5 MB. Loads the bytes twice (formulas + cached values). Finds the sheet (`BulkOrders`, else first sheet with headers) and the header row (rows 1–10 with `NSN` and `Description`). Maps columns, normalizes values, collects row errors. Reads the export stamp (J1 `STATZ Export`, K1 ISO UTC → `exported_at`). |
| `matcher.py` | `build_plan()`: matches rows to items, builds the JSON plan; `removal_ack_required()`, `plan_counts()`, `display_updates()`. |
| `apply.py` | `create_run()`, `discard_run()`, `apply_run()` (one `transaction.atomic()`). |
| `exporter.py` | `build_export()` → `(Inventory_Tracker_{YYYY-MM-DD}.xlsx, bytes)`. |
| `banner.py` | `sync_banner()`: one query, used by the dashboard and the add/edit form. |

openpyxl is reached only through `contracts/utils/excel_utils.py`, imported inside functions.

### Column map (header text trimmed, case-insensitive, spaces collapsed)
| Header text(s) | Field |
|---|---|
| `nsn` | `nsn` |
| `description` | `description` |
| `part number`, `part #`, `part no`, `partnumber` | `partnumber` |
| `manufacturer` | `manufacturer` |
| `quantity`, `qty` | `quantity` |
| `quantity remaining`, `qty remaining`, `remaining` | `quantity_remaining` |
| `purchase price`, `unit price`, `price` | `purchaseprice` |
| `location` | `itemlocation` |
| `statz id` / `statz version` | match helpers |
| `total cost` | recognized, ignored |

Required: NSN, Description, Quantity, Purchase Price. With no `location` header, the column right of the right-most recognized header is the location if its header is blank (her column I). Location: blank → `In House`; contains `quality support` → `Quality Support`; else strip `*` and `housed at `. Rows with NSN / Description / Part Number / Manufacturer / Quantity all blank are skipped, as are rows containing `TOTAL` or `ON-HAND VALUE`. Text over the field's `max_length`, negative or non-numeric numbers, and formulas without a cached value are row errors; any error fails the whole run (no partial applies).

### Matching
1. By `STATZ ID` when it exists in the DB. A repeated ID: the top-most row keeps it, later rows become adds (warning). An ID not in the DB becomes an add (warning: deleted in STATZWeb).
2. By key (`nsn.upper()`, `partnumber.upper()`, `round(price, 2)`) when exactly one unmatched row and one unmatched item share it.
3. Remaining rows → **add** (`is_public=False`).
4. Remaining items → **keep** when the file has an export stamp and `last_modified > exported_at`; otherwise **remove**.

A matched row is an **update** when any sheet-owned field differs (price compared at 4 dp), else **unchanged**. A matched row whose `STATZ Version` is older than `last_modified` is flagged as a conflict. Removing a public item is flagged. Removals > 5 and > 25% of items require the "I understand N items will be removed." checkbox (enforced in `apply_run`).

**Sheet-owned fields:** `nsn`, `description`, `partnumber`, `manufacturer`, `itemlocation`, `quantity`, `quantity_remaining`, `purchaseprice`. **STATZWeb-owned:** `id`, `is_public` (never changed by sync), `totalcost` and `last_modified` (computed by `save()`).

### Apply
Refused (run marked `discarded`, "Inventory changed since this preview. Please upload your file again.") unless the run is `preview`, no other run was applied after it was created, no item has `last_modified` after it was created, every updated item still exists, and the large-removal checkbox was ticked when required. Then, in one `transaction.atomic()`: removes (`filter(id__in=chunk).delete()`), updates (`in_bulk` + `.save()` each), adds (`.save()` each in sheet order), run → `applied`. **Never bypass `save()` in sync** (no `queryset.update()`, `bulk_create`, `bulk_update`).

### Export
`BulkOrders`: A1 `Current Inventory`, J1 `STATZ Export`, K1 export time (ISO UTC). Row 2 headers A–K (black fill, white bold, centered, thin borders), Aptos Narrow 11 everywhere, J/K hidden, freeze panes A3, autofilter `A2:I{last}`. One row per item by `id`; H = `=IF(OR(E="",G=""),"",E*G)`; G/H currency format. Two rows below the data: `TOTAL` (`=SUM(H…)`) and `ON-HAND VALUE` (`SUMPRODUCT` of remaining-or-quantity × price). Every other sheet from the latest applied run's file (e.g. `PurchaseOrders`) is copied after it with values, formulas, number formats, fonts, fills, alignment, merges, and column widths.

### Banner
When the latest applied run is within 60 days, the dashboard and add/edit form show an `alert-info`: "Inventory is synced from {name}'s spreadsheet (last sync {date}). …" (`created_by` full name, else username).


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode token overrides when `[data-bs-theme="dark"]` is on `<html>`, as set by `static/js/theme_toggle.js`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here. Inventory dashboard classes are prefixed `inv-`.
- `static/css/utilities.css` — utility and helper classes.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
