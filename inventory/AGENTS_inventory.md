# AGENTS_inventory.md — inventory
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

Read `inventory/CONTEXT_inventory.md` first. This file does not repeat that content; it defines safe-edit rules grounded in the actual code.

---

## 1. Purpose of This File

This file tells AI coding agents how to safely modify the `inventory` app: coupled files, breakage risks, cross-app dependencies, and the patterns to follow.

---

## 2. App Scope

**Owns:** The warehouse stock ledger — `InventoryItem` rows in `STATZ_WAREHOUSE_INVENTORY_TBL`; CRUD, autocomplete, computed `totalcost`, the `is_public` opt-in flag, `quantity_remaining` / `on_hand`, `inventory/selectors.py`, the read-only public API in `inventory/api/`, and the spreadsheet sync (`InventorySyncRun`, `inventory/sync/`).

**Does not own:** Authentication (`STATZWeb/decorators.py`, `STATZWeb/middleware.py`), base navigation (`templates/base_template.html`), the `statzcorp-com` site that consumes the API, or `crispy_forms` / jQuery UI.

**Classification:** Small operational app with no cross-app model dependencies. No other installed app imports from `inventory`. External coupling: nav links in `base_template.html`, the two URL includes in `STATZWeb/urls.py`, the public URL entry in `STATZWeb/middleware.py`, and the `statzcorp-com` API consumer.

---

## 3. Read This Before Editing

### Before changing models
- `inventory/models.py` — null-safe `save()`; `__str__` is a real model method.
- `inventory/migrations/` — `0001`–`0006`; new ones must chain from `0006_inventory_sync`.
- `inventory/sync/parser.py` `SHEET_FIELDS` / `TEXT_FIELDS` — adding a sheet-owned field means parser, matcher, exporter columns, and tests together.
- `inventory/forms.py` — `exclude = ['id', 'totalcost']`; `is_public` label and widget are set here.
- `inventory/api/serializers.py` — the API allowlist; adding a model field does NOT add it to the API.

### Before changing views / selectors
- `inventory/selectors.py` — shared by the dashboard and the API. A change to `_search_q` affects both.
- `inventory/views.py` — `DASHBOARD_COLUMNS` and `PER_PAGE_CHOICES` drive the table headers and toolbar.
- `STATZWeb/decorators.py` — every inventory UI view uses `conditional_login_required`.

### Before changing the API
- `inventory/api/auth.py`, `inventory/api/views.py`, `inventory/INVENTORY_API.md`, `inventory/tests.py`.
- `suppliers/portal/auth.py` — the reference signing scheme. Copy the pattern; never import it.

### Before changing templates / JS
- `inventory/templates/inventory/dashboard.html` — no inline JS or CSS; `data-inv-*` attributes are the JS hooks.
- `inventory/static/inventory/js/inventory_dashboard.js` — reads `data-inv-delete-url`, `data-inv-delete-label`, `data-inv-autosubmit`, and the modal's CSRF input.
- `inventory/templates/inventory/item_form.html` — fields are rendered by name. Autocomplete inputs carry `data-autocomplete-url` (built with `{% url %}`); `inventory_form.js` reads that attribute. Do not hardcode those paths in the JS file.
- `templates/base_template.html` — two `{% url 'inventory:dashboard' %}` links.

---

## 4. Local Architecture / Change Patterns

- **Query logic lives in `selectors.py`.** Views and API views call selectors; they do not build their own filters.
- **Dashboard is server-side.** Search, filter, sort, and pagination happen in SQL. No client-side sorting.
- **API is a self-contained package (`inventory/api/`).** It imports only from `inventory.selectors` and its own modules.
- **`InventoryItem.save()` owns `totalcost`** (null-safe, quantity × price) and `auto_now` owns `last_modified`. `on_hand` / `on_hand_value` are read-only properties.
- **Sync business logic lives in `inventory/sync/`.** Views only call `create_run`, `apply_run`, `discard_run`, `build_export`, `sync_banner`, and the `matcher` display helpers.
- **The form has no crispy layout.** `InventoryItemForm` does not build a `FormHelper`. `BaseFormMixin` still injects placeholders; `InventoryItemForm.__init__` strips them and sets `form-control` / `form-check-input`. Do not edit the mixin for this form.

---

## 5. Files That Commonly Need to Change Together

### Adding a model field
`models.py` → new migration → `forms.py` → `item_form.html` → (if shown on the dashboard) `views.py` `DASHBOARD_COLUMNS` + `selectors.py` `SORT_FIELDS` + `dashboard.html` row cell. Do not touch `api/serializers.py` unless the field is reviewed for public exposure.

### Renaming a URL or view
`urls.py` → `views.py` → `dashboard.html` / `item_form.html` `{% url %}` tags → `base_template.html` nav links.

### Changing autocomplete
`views.py` (`autocomplete_*`) → `urls.py` → `item_form.html` `data-autocomplete-url` → `inventory_form.js` → `forms.py` widget classes (`autocomplete-nsn`, `autocomplete-description`, `autocomplete-manufacturer`).

### Changing `totalcost` / KPI math
`models.py` `save()` / `on_hand` → `selectors.py` `inventory_kpis()` → `dashboard.html` KPI cards → `sync/exporter.py` TOTAL / ON-HAND VALUE formulas.

### Changing the sync
`sync/parser.py` (column map, normalization) ↔ `sync/exporter.py` (`HEADERS`, column order) ↔ `sync/matcher.py` (plan shape) ↔ `sync/apply.py` (plan consumer) ↔ `sync_preview.html` (plan keys) ↔ `tests_sync.py`. The exporter's headers must stay recognizable by the parser, or round trips break.

### Changing the API contract
`api/views.py` / `api/serializers.py` → `INVENTORY_API.md` → `tests.py` → notify the `statzcorp-com` developer.

---

## 6. Cross-App Dependency Warnings

**This app depends on:**
- `STATZWeb/decorators.py` — `conditional_login_required`.
- `STATZWeb/middleware.py` — `LoginRequiredMiddleware.public_urls` must keep `/api/inventory/v1/`.
- `STATZWeb/settings.py` — `REQUIRE_LOGIN`, `INVENTORY_API_KEY`, `INVENTORY_API_HMAC_SECRET`.
- `STATZWeb/urls.py` — includes `inventory.urls` and `inventory.api.urls` (namespace `inventory_api`).
- `products/nsn_utils.py` — `nsn_query_variants()` (imported lazily inside selectors).
- `contracts/utils/excel_utils.py` — the only way to reach openpyxl. Import it inside functions; never `import openpyxl` anywhere.
- `templates/base_template.html` — Bootstrap 5.3 JS, Bootstrap Icons, jQuery, jQuery UI.

**Other apps that depend on this app:** none in-repo. `statzcorp-com` depends on the API contract.

---

## 7. Security / Permissions Rules

- Every UI view (dashboard, add, edit, delete, autocomplete) has `@conditional_login_required`. Do not remove it.
- The dashboard delete posts with `X-CSRFToken` and `credentials: 'same-origin'`. Preserve that contract.

### Public inventory API rules
- **Never expand the API field allowlist** (`id`, `nsn`, `description`, `part_number`, `manufacturer`, `quantity`) without review. `quantity` is `item.on_hand`; `quantity_remaining`, `last_modified`, and `is_public` are never serialized.
- API list order is `blank_nsn` (Case: blank/NULL NSN → 1), `nsn`, `id`. Keep `id` last for deterministic MSSQL paging.
- **Never expose `purchaseprice`, `totalcost`, or `itemlocation`** through the API, in serialization, error bodies, or search (`public_items_queryset` must not search location).
- Never serialize with `model_to_dict` or an all-fields `values()`. Use `serialize_public_item`.
- Only `is_public=True` rows. Non-public and missing items both return `404 {"error": "not_found"}`.
- Auth mirrors `suppliers/portal/auth.py` exactly (canonical string, ±300 s, 401 body shape). Use `hmac.compare_digest`. If either secret is unset, return 401 (fail closed). Never log secrets, keys, or signatures.
- Separate secrets: `INVENTORY_API_KEY`, `INVENTORY_API_HMAC_SECRET`. Never reuse the supplier portal secrets.
- GET only; non-GET returns 405 after auth. Views are `csrf_exempt` (HMAC replaces CSRF).
- No CORS headers. Every response carries `Cache-Control: no-store`.
- Do not import from `suppliers.*`.
- The middleware bypass entry is exactly `/api/inventory/v1/`. Never widen it.

---

## 8. Model and Schema Change Rules

- `db_table = 'STATZ_WAREHOUSE_INVENTORY_TBL'` must not change without DBA coordination.
- Legacy fields have explicit `db_column` mappings; keep them when renaming attributes.
- `totalcost` is `editable=False` and excluded from the form.
- `purchaseprice`/`totalcost` stay `FloatField`. Do not add indexes on `is_public` (low cardinality).
- **NSN is not unique.** Never add a unique constraint or unique index on `nsn` (same-NSN lots and blank NSNs are real data). No column uniquely identifies a sheet row; sync matches by `STATZ ID`, then key.
- `InventorySyncRun` rows are never deleted by code. Never list `file_bytes` in admin or page list queries (`defer('file_bytes')`).
- Run `makemigrations` after field changes; never edit applied migrations.

---

## 9. View / URL / Template Change Rules

- URL names `dashboard`, `add_item`, `edit_item`, `delete_item`, `autocomplete_nsn`, `autocomplete_description`, `autocomplete_manufacturer`, `sync_home`, `sync_upload`, `sync_preview`, `sync_apply`, `sync_discard`, `sync_export` are referenced by string in templates.
- Sync views keep `@conditional_login_required`; upload / apply / discard also keep `@require_POST`. The sync pages need no JS; sync CSS uses the `inv-sync-` prefix.
- Dashboard query params (`q`, `vis`, `sort`, `dir`, `page`, `per_page`) are whitelisted. Anything unknown falls back silently; keep `id` as the ordering tiebreaker (MSSQL OFFSET/FETCH needs a deterministic order).
- Materialize the page rows with `list(page_obj.object_list)` before calling `inventory_kpis()` (no MARS).
- Dashboard JS lives in `static/inventory/js/inventory_dashboard.js`. Do not add inline `<script>` blocks. New CSS goes in `static/css/app-core.css` with the `inv-` prefix, colors via variables only.

---

## 10. Forms / Serializers / Input Validation Rules

- `InventoryItemForm` has no `clean()`. Blank quantity/price are allowed; `save()` handles them.
- All labels live in `InventoryItemForm.Meta.labels`. The template prints `{{ form.<name>.label }}`. There are no label-string comparisons.
- `clean_quantity` and `clean_purchaseprice` reject negatives. Both fields stay optional. Blank input saves as `None`.
- Add mode posts `_addanother` to return to the add form. Edit mode has no such button; do not honor that field there.
- API serializer: `inventory/api/serializers.py` only. Null strings → `""`, null quantity → `0`.

---

## 11. Background Tasks / Signals / Automation Rules

None.

---

## 11a. Spreadsheet Sync Rules

Full reference: `CONTEXT_inventory.md` §20 (flow, column map, matching, export layout).

- **Master copy:** on rows the file knows about, the spreadsheet wins. Items added/edited on the page after the file's export stamp (`last_modified > exported_at`) are **kept**. Without a stamp (her original file), unmatched items are removed.
- **Sheet-owned:** `nsn`, `description`, `partnumber`, `manufacturer`, `itemlocation`, `quantity`, `quantity_remaining`, `purchaseprice`. **Never changed by sync:** `id`, `is_public`. New items get `is_public=False`.
- **Never bypass `save()` in sync.** No `queryset.update()`, `bulk_create`, or `bulk_update` in `inventory/sync/` (they skip `totalcost` and `last_modified`). Removes use `filter(id__in=chunk).delete()`.
- `apply.py` has exactly one `transaction.atomic()`. No partial applies: any row error fails the run.
- Apply-time staleness checks (status, later applied run, later `last_modified`, missing items, large-removal checkbox) run inside that block and discard the run on failure. Keep them server-side.
- Materialize items with `list(...values())` before secondary queries (no MARS). Chunk `id__in` lists (`IN_CHUNK = 500`).
- Matching key is `(nsn.upper(), partnumber.upper(), round(price, 2))`, only when exactly one row and one item share it.
- Exporter `HEADERS` and the parser's `HEADER_MAP` must stay in step; J1/K1 stamp and hidden J/K columns are how round trips work.
- Never log file contents or row values at INFO or above.
- The banner helper (`sync/banner.py`) is one query; both the dashboard and the add/edit form use it.

---

## 12. Testing and Verification Expectations

Run `python manage.py test inventory` (SQLite; runs `tests.py` and `tests_sync.py`). Coverage is listed in `CONTEXT_inventory.md` §15. `tests_sync.py` builds Cori-style workbooks in-test through `excel_utils`; extend those fixtures rather than adding binary files. When changing the API or the middleware entry, also run `STATZWeb.tests.test_login_required_middleware`.

**Manual checks after UI changes:**
1. `/inventory/` renders KPI cards and the table; search debounce, visibility, and per-page selects reload the list.
2. Column headers sort server-side and keep the current filters; pagination keeps all params.
3. Delete opens the modal, deletes, and reloads; a failure shows the inline alert.
4. Add/edit form autocomplete works; "Show on public website" saves.
5. Dark mode renders correctly.

---

## 13. Known Footguns

- **Selectors are shared.** A search change for the dashboard also changes the API unless you scope it to `DASHBOARD_TEXT_FIELDS`.
- **Signing changes break `statzcorp-com`.** The canonical string, header names, and window must match `INVENTORY_API.md`.
- **Removing `/api/inventory/v1/` from `public_urls`** turns every API call into a login redirect when `REQUIRE_LOGIN` is on.
- **`base_template.html` has two hardcoded `inventory:dashboard` links.**
- **Autocomplete URLs live in the template, not the JS.** `inventory_form.js` only reads `data-autocomplete-url`. Renaming an autocomplete URL means updating the `{% url %}` in `item_form.html`.

---

## 14. Safe Change Workflow

1. Read `inventory/CONTEXT_inventory.md` and this file.
2. Read the files involved (models, selectors, views, api, templates).
3. Make the minimal scoped change; update coupled files together (Section 5).
4. Run `python manage.py test inventory`, `check`, `makemigrations --check --dry-run`.
5. If the API contract changed, update `INVENTORY_API.md`.

---

## 15. Quick Reference

| Area | Primary Files |
|---|---|
| Model + schema | `inventory/models.py`, `inventory/migrations/` |
| Shared queries | `inventory/selectors.py` |
| UI views | `inventory/views.py` |
| URL names | `inventory/urls.py` |
| Public API | `inventory/api/` (`auth.py`, `serializers.py`, `views.py`, `urls.py`) |
| API contract | `inventory/INVENTORY_API.md` |
| Form | `inventory/forms.py`, `inventory/templates/inventory/item_form.html`, `inventory/static/inventory/js/inventory_form.js` |
| Dashboard UI + JS | `inventory/templates/inventory/dashboard.html`, `inventory/static/inventory/js/inventory_dashboard.js` |
| Currency formatting | `inventory/templatetags/custom_filters.py` |
| Auth | `STATZWeb/decorators.py`, `STATZWeb/middleware.py` |
| Spreadsheet sync | `inventory/sync/` (`parser.py`, `matcher.py`, `apply.py`, `exporter.py`, `banner.py`), `sync_home.html`, `sync_preview.html`, `_sync_banner.html` |
| Tests | `inventory/tests.py`, `inventory/tests_sync.py` |


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles (inventory classes use the `inv-` prefix)
- `static/css/utilities.css` — utility and helper classes

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
