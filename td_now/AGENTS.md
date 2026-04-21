# AGENTS.md — `td_now`
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

Read `td_now/CONTEXT.md` first. This file defines safe-edit guidance and does not repeat what is already there.

---

## 1. Purpose of This File

This file tells AI coding agents and future developers how to modify `td_now` safely. It documents tightly coupled file clusters, known active bugs, security boundaries, and verification steps that must happen after any non-trivial change.

---

## 2. App Scope

**Owns:**
- All tower-defense domain models: `Map`, `PathNode`, `BuildSpot`, `TowerType`, `TowerLevel`, `EnemyType`, `Wave`, `WaveEnemy`, `Campaign`, `CampaignStage`, `StageWave`, `StageWaveGroup`
- JSON APIs serving game state and editor data
- Canvas game engine (`main.js`) and all editor JS (`builder.js`, `campaign_builder.js`, `asset_editor.js`, `campaign_select.js`)
- Staff-only map/campaign/asset editors under `@login_required`
- Seed data via `management/commands/seed_td_now.py`

**Does not own:**
- Authentication — uses Django's built-in `@login_required` only
- Any cross-app business logic; no other app imports from `td_now`
- The global base template (`base_template.html`) — all `td_now` templates extend it but do not own it
- Any scheduled jobs, signals, or Celery tasks

**App type:** Self-contained feature mini-app. No other installed app depends on `td_now` models. External dependency is only `scripts/inspect_campaigns.py` (a diagnostic script, not a production dependency).

---

## 3. Read This Before Editing

### Before changing models
- `td_now/models.py` — understand cascade deletes (all child rows are CASCADE from `Map`; `Campaign` stages cascade to `StageWave`/`StageWaveGroup`)
- `td_now/views.py` — every JSON property name in the API payloads must stay in sync with field names; look at `level_detail` and `campaign_detail` especially
- `td_now/static/td_now/main.js` — the game engine reads camelCase property names like `startMoney`, `fireRate`, `spawnInterval`, `iconShape`, `iconColor`, `iconHitColor`, `beamDash` directly from the JSON
- `td_now/migrations/` — check the last migration before adding new fields
- `td_now/admin.py` — `list_display` and inlines reference model fields by name

### Before changing views / JSON APIs
- `td_now/static/td_now/main.js` — verify exact property names consumed (e.g., `startMoney`, `startLives`, `buildSpots`, `towerTypes`, `enemyTypes`, `waves`, `groups`, `typeId`, `spawnInterval`, `startDelay`)
- `td_now/static/td_now/builder.js` — calls `/td-now/api/maps/` (POST) and `/td-now/api/maps/<id>/` (PUT); checks `id` in response
- `td_now/static/td_now/campaign_builder.js` — calls create/update campaign endpoints; builds payloads with `mapId`, `useMapWaves`, `wavesToPlay`, `startMoneyOverride`, `startLivesOverride`, `groups[].typeId`, `groups[].spawnInterval`, `groups[].startDelay`
- `td_now/static/td_now/asset_editor.js` — calls tower and enemy CRUD endpoints; sends `fireRate` (not `fire_rate`), `iconShape`, `iconColor`, `iconBlinkColor`, `iconHitColor`, `beamColor`, `beamWidth`, `beamDash`

### Before changing templates
- `td_now/templates/td_now/builder.html` — has a known mismatched `<div>` closing tag near the save/update buttons (documented known gap); inspect before editing surrounding structure
- All templates use a `cache_version` query string on JS includes; update it after any static file changes if cache-busting is needed

### Before changing the seed command
- `td_now/management/commands/seed_td_now.py` — uses `get_or_create` by name for maps/campaigns and hard-codes enemy names (`"Grunt"`, `"Runner"`, `"Tank"`, `"Boss"`) via `name__iexact` lookups; if you rename seeded objects in the DB, the seed will diverge

---

## 4. Local Architecture / Change Patterns

- **No forms.py, no serializers.py.** All input validation is manual in `views.py` using `json.loads` + type coercion. Keep this pattern; do not move validation into models or introduce serializers without coordinating with the JS clients.
- **Views are thin renderers or JSON responders.** Page views just call `render`. API views do all logic inline. There is no service layer.
- **All JSON keys are camelCase on the wire, snake_case in models.** The mapping is manual in each view. Mismatches are silent bugs at runtime.
- **Update operations always wipe-and-recreate child rows.** `update_map` deletes all `PathNode`/`BuildSpot` rows before bulk-creating. `update_campaign` deletes all stages before recreating. This is intentional and destructive — do not add soft deletes or diffing without understanding the JS editors' save behavior.
- **Admin is used for data management**, not just read-only inspection. The `TowerLevelInline` under `TowerTypeAdmin` and the `WaveEnemyInline` under `WaveAdmin` are real workflows for staff.
- **JS clients are the canonical editors.** The Django admin should not be used for `PathNode`/`BuildSpot` management in production — `builder.js` is the authoritative editor for those.

---

## 5. Files That Commonly Need to Change Together

### Adding a field to a model
`models.py` → new migration → `views.py` (add to JSON payload) → relevant JS file (consume or send the field) → `admin.py` (add to `list_display` if useful) → `seed_td_now.py` (if it has a default seed value)

### Changing a `TowerType` or `TowerLevel` field
`models.py` → migration → `views.py:level_detail` → `views.py:campaign_detail` → `views.py:towers_list` → `views.py:towers_create` → `views.py:towers_update` → `static/td_now/main.js` (reads tower data) → `static/td_now/asset_editor.js` (CRUD editor) → `admin.py`

### Changing an `EnemyType` field
`models.py` → migration → `views.py:enemies_list` → `views.py:enemies_create` → `views.py:enemies_update` → `views.py:level_detail` → `views.py:campaign_detail` → `static/td_now/main.js` → `static/td_now/asset_editor.js` → `admin.py`

### Changing `StageWaveGroup` fields
`models.py` → migration → `views.py:campaign_detail` (the `groups` list payload) → `views.py:create_campaign` / `update_campaign` (intake) → `static/td_now/campaign_builder.js` (DOM + payload builder) → `static/td_now/main.js` (reads `startDelay`, `spawnInterval`, `typeId`)

### Adding a new URL/view
`views.py` → `urls.py` → relevant template and/or JS file

### Changing the game engine simulation logic
`static/td_now/main.js` only — but verify the JSON shapes it reads have not changed in `views.py`

---

## 6. Cross-App Dependency Warnings

- **`STATZWeb/settings.py`**: includes `td_now.apps.TDNowConfig` — app must stay importable
- **`STATZWeb/urls.py`**: mounts `td_now.urls` at `/td-now/` — the `app_name = 'td_now'` namespace is used for URL reversals; do not change it
- **`scripts/inspect_campaigns.py`**: imports `td_now.models` directly. If models are renamed or moved, this script will break. It is a diagnostic tool (not production), but worth noting.
- **No other installed app imports from `td_now`** — confirmed by repo-wide search. This app has no reverse dependencies in the production codebase.
- **`base_template.html`**: all five `td_now` templates extend it; if the base template changes block names or layout, `td_now` templates may break silently

---

## 7. Security / Permissions Rules

- **Never remove `@login_required`** from `builder`, `campaign_builder`, `asset_editor`, `create_map`, `update_map`, `towers_create`, `towers_update`, `enemies_create`, `enemies_update`, `create_campaign`, `update_campaign`. These are mutation endpoints and must remain staff-only.
- **Public GET endpoints** (`levels_list`, `level_detail`, `enemies_list`, `towers_list`, `campaigns_list`, `campaign_detail`) are intentionally open. Do not add auth to them without also updating `main.js` and `campaign_select.js` (which call them without credentials).
- **CSRF is enforced** on all mutation views via Django middleware. The JS clients send `X-CSRFToken` from cookies. Do not add `@csrf_exempt` to mutation views.
- **No object-level permissions** are implemented. Any logged-in user can modify any tower, map, or campaign. If multi-tenancy is ever added, a full review of all mutation views is required.
- **`views.py` uses `get_object_or_404`** for all FK lookups in create/update views — preserve this behavior when adding new endpoints.

---

## 8. Model and Schema Change Rules

- **Before renaming any field**, search `views.py` for both the snake_case DB name and the camelCase wire name; then search all five JS files for the camelCase name. Mismatches fail silently in the browser.
- **CASCADE deletes are wide.** Deleting a `Map` cascades to `PathNode`, `BuildSpot`, `Wave` (and its `WaveEnemy` rows), and `CampaignStage` (which cascades to `StageWave` → `StageWaveGroup`). Document this in any migration that touches `Map` or adds FKs to it.
- **`TowerLevel` has `unique_together = ("tower_type", "level_number")`.** Any migration affecting this constraint must handle existing data.
- **Do not remove `ordering` meta from `PathNode` (`order_index`), `Wave` (`wave_number`), or `StageWave` (`wave_number`).** The game engine depends on ordered paths; removing ordering will produce scrambled enemy paths.
- **After adding model fields**, run `python manage.py seed_td_now` to verify the seed command still works. The seed uses `get_or_create` and may silently skip new fields if they have no defaults.

---

## 9. View / URL / Template Change Rules

- **URL `name` values are the stable contract.** `app_name = 'td_now'` is set in `urls.py`. Do not change URL names without searching templates and any `reverse()` calls across the project.
- **The root URL `''` maps to `campaign_select`**, not `index`. The `index` view renders `index.html` (the canvas game) and is mounted at `play/`. This is counterintuitive — do not swap them.
- **`/td-now/api/campaigns/create/` must be listed before `/td-now/api/campaigns/<int:campaign_id>/` in `urls.py`** — it currently is. If reordering URL patterns, verify the `create/` literal path is not shadowed by the `<int:campaign_id>/` pattern.
- **Template context is minimal.** Most views only pass `{"title": "..."}`. All data loading happens in JS via the JSON APIs. Do not add server-side context expecting the templates to use it without also updating the JS.
- **`cache_version`**: templates append `?v={{ cache_version }}` to JS includes. This variable must be provided by the base template or a context processor; check if it exists before adding new JS includes.
- **`builder.html` has mismatched `<div>` tags** near the save/update buttons — a known bug. Be cautious editing that section of the template.

---

## 10. Forms / Serializers / Input Validation Rules

- There are no Django forms or DRF serializers in this app. All validation is manual in `views.py`.
- Input coercion uses `int()` / `float()` with `or <default>` fallback (e.g., `int(data.get('cost') or 0)`). This means `0` is a valid but sometimes nonsensical value — no range validation is done.
- If you add a new field to a create/update view, follow the same pattern: `int(data.get('fieldName') or default)`. Do not introduce serializers without also updating the JS clients that build the payloads.
- Wire-format names must be camelCase to match what JS sends. Model field names are snake_case. The translation is in each view function.

---

## 11. Background Tasks / Signals / Automation Rules

- **No signals, no Celery tasks, no cron jobs, no async behavior.** Everything is synchronous request/response.
- `management/commands/seed_td_now.py` is the only automation hook — run it manually via `python manage.py seed_td_now` after setup or after destructive data changes.
- There are no post-save / post-delete signal receivers anywhere in `td_now`.

---

## 12. Testing and Verification Expectations

- **No tests exist** (`tests.py` is absent; no `tests/` directory). All verification is manual.
- After any model/view change, manually verify:
  1. `/td-now/` loads without JS errors (open browser console)
  2. `/td-now/api/levels/<id>/` returns the correct JSON shape
  3. `/td-now/api/campaigns/<id>/` returns the correct JSON shape
  4. The canvas game starts a wave without errors
  5. `/td-now/builder/` (staff login) can save and load a map
  6. `/td-now/assets/` (staff login) can create and update a tower and enemy
  7. `/td-now/campaign-builder/` (staff login) can save a campaign
- After changing `EnemyType` or `TowerType` fields, verify the asset editor still renders the row correctly and the save payload includes the changed field.
- After changing `StageWaveGroup`, verify campaign JSON includes `startDelay`, `spawnInterval`, `typeId`, and `count` in the `groups` array.
- Run `python manage.py seed_td_now` and confirm it completes without errors after any model change.

---

## 13. Known Footguns

1. **`CampaignEngine` is broken.** `static/td_now/main.js` has a `return;` that prevents `CampaignEngine` from ever running, and the class is defined after the IIFE closes (likely causing a `ReferenceError`). Campaign play mode does not work. Do not assume it does when testing.

2. **`campaign_builder.js` defines `async function save()` twice.** The second definition silently overrides the first. The effective save function is the second one. If you add logic to the "first" save, it is unreachable. Verify which definition is active before editing.

3. **JSON key names are the integration contract.** Renaming a model field without updating all camelCase references in `views.py` and all five JS files causes silent failures — data just doesn't appear or save correctly in the browser, with no server-side error.

4. **`update_campaign` and `update_map` are destructive by design.** They delete all child rows before recreating them. A partial payload (missing stages or path nodes) will permanently erase data. Do not call these from scripts without full payloads.

5. **`seed_td_now.py` uses name-based lookups** (`name__iexact="Grunt"`) to find existing enemies. If someone renames seeded enemies in the admin, the seed command will create duplicates instead of updating them.

6. **`TowerLevel` upgrades are not included in `towers_list`** (only base stats are). The full level data (with multipliers) is only in `level_detail` and `campaign_detail`. Do not assume `towers_list` is the full tower spec.

7. **`views.py` uses `@csrf_exempt` is absent** — this is correct and must stay that way. If you see a `403 Forbidden` on a mutation, the fix is to send the CSRF token in JS, not to add `@csrf_exempt`.

8. **`builder.html` has a mismatched `<div>` closure** near the save/update buttons. Editing that section without careful bracket counting will break the layout.

9. **No pagination on list endpoints.** `levels_list`, `towers_list`, `enemies_list`, `campaigns_list` return all rows. If the database grows large, these will become slow. Do not add filtering logic to JS without also adding it to the view.

---

## 14. Safe Change Workflow

1. Read `td_now/CONTEXT.md` for domain overview
2. Read the specific files involved in your change (`models.py`, `views.py`, relevant JS)
3. Identify the camelCase wire names for any field you are touching
4. Search all five JS files for those camelCase names to find all consumers
5. Make the minimal model/view/JS change
6. Update coupled files: migration → view payload → JS consumer → admin `list_display` if needed
7. Run `python manage.py seed_td_now` to verify the seed still works
8. Manually open `/td-now/api/levels/1/` (or the relevant endpoint) and confirm the JSON shape is correct
9. Open the browser and verify no JS console errors on the affected page
10. If you changed a mutation endpoint, test it via the relevant staff editor page

---

## 15. Quick Reference

| Area | Primary Files |
|---|---|
| Domain models | `td_now/models.py` |
| API + page views | `td_now/views.py` |
| URL routing | `td_now/urls.py` |
| Admin | `td_now/admin.py` |
| Canvas game engine | `td_now/static/td_now/main.js` |
| Map builder editor | `td_now/static/td_now/builder.js` |
| Campaign editor | `td_now/static/td_now/campaign_builder.js` |
| Asset editor | `td_now/static/td_now/asset_editor.js` |
| Campaign select UI | `td_now/static/td_now/campaign_select.js` |
| Templates | `td_now/templates/td_now/*.html` |
| Seed command | `td_now/management/commands/seed_td_now.py` |
| External diagnostic | `scripts/inspect_campaigns.py` |

**Main coupled areas:** model field ↔ `views.py` JSON key ↔ camelCase JS property — all three must stay in sync.

**Cross-app dependencies:** `STATZWeb/settings.py` (app installed), `STATZWeb/urls.py` (mounted at `/td-now/`), `scripts/inspect_campaigns.py` (imports models directly).

**Security-sensitive areas:** All `@login_required` mutation views — never remove or weaken. Public GET endpoints — never add auth silently.

**Riskiest edit types:**
- Renaming model fields (silent JSON mismatch)
- Editing `main.js` campaign/wave logic (broken `CampaignEngine` already present)
- Editing `campaign_builder.js` save logic (duplicate function definition)
- Editing `builder.html` around save buttons (mismatched `<div>` tags)
- Calling `update_campaign` or `update_map` with partial payloads (destroys child rows)


## CSS / Styling Rules

This project does not use Tailwind in any form. All styling uses Bootstrap 5 plus the project's three-file CSS architecture:

- `static/css/theme-vars.css` — color tokens and dark mode overrides only
- `static/css/app-core.css` — all component, layout, and button styles
- `static/css/utilities.css` — utility and helper classes

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When editing templates:** if you encounter Tailwind utility classes, replace them with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind classes in place.

**Button pattern:** `.btn-outline-brand` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for pill-style with `#eff6ff` background tint.
