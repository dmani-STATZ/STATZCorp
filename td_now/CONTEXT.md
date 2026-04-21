# TD Now Context

## 1. Purpose
TD Now is a self-contained tower-defense mini-game bundle inside STATZCorp. It owns the data structures for maps, path nodes, builds, towers, enemies, waves, and campaigns, and it serves both the playable canvas (`/td-now/play/`) and the supporting editors used by staff to curate content (`builder`, `campaign_builder`, `asset_editor`). The app lets players run single maps or whole campaigns, while giving staff the ability to create or tweak maps, towers, enemies, and campaigns through dedicated UI backed by JSON APIs.

## 2. App Identity
- Django app name: `td_now` and AppConfig `TDNowConfig` (`td_now/apps.py`).
- Filesystem path: `td_now/` within the repository root.
- Role: feature-rich mini-game / experimental feature app that operates alongside the main site rather than being a platform-wide shared library or report engine.

## 3. High-Level Responsibilities
- Own all tower-defense domain objects: `Map`, `PathNode`, `BuildSpot`, `TowerType`, `EnemyType`, `Wave`, `WaveEnemy`, `TowerLevel`, `Campaign`, `CampaignStage`, `StageWave`, and `StageWaveGroup`.
- Provide game-facing views (`index`, `campaign_select`, `play`) plus JSON endpoints that supply the level/campaign data the browser needs.
- Power the builder/campaign-editor/asset-editor experiences by wiring GET/POST/PUT endpoints and restricting mutations to logged-in staff.
- Render the client-side UI (templates in `templates/td_now/` plus `static/td_now` JS/CSS) and host the full vanilla-JS canvas game engine (`static/td_now/main.js`).
- Seed sample content via `management/commands/seed_td_now.py` to ensure there is always at least one playable map/campaign.

## 4. Key Files and What They Do
- `models.py`: declares the full domain; towers and enemies include visual/growth metadata, `CampaignStage` can reuse map waves or define custom `StageWaveGroup`s, and `TowerLevel` captures level-specific AoE modifiers.
- `views.py`: renders the templates, exposes `@require_http_methods` JSON APIs for levels, campaigns, maps, towers, and enemies, and enforces login on editors/mutations.
- `urls.py`: mounts the UI and API endpoints under the `td-now` URL namespace (e.g., `/td-now/api/levels/`, `/td-now/campaign-builder/`).
- `admin.py`: registers every domain model, nests `TowerLevel` inline under `TowerType`, `WaveEnemy` under `Wave`, `StageWaveGroup` under `StageWave`, and exposes filters/list displays for Maps, CampaignStages, Waves, etc.
- `static/td_now/main.js`: contains the entire HTML5 canvas `GameEngine`, rendering, tower targeting, infinite mode wave generator, and the unfinished `CampaignEngine` wrapper.
- `static/td_now/builder.js`, `campaign_builder.js`, `asset_editor.js`, `campaign_select.js`: implement the interactive editors that talk to the JSON APIs.
- `templates/td_now/*.html`: serverside pages that load the appropriate JS bundle plus `td_now/style.css` and extend the global `base_template.html`.
- `management/commands/seed_td_now.py`: bootstraps a default map/towers/enemies/waves/campaign so `/td-now/` is playable right after setup.

## 5. Data Model / Domain Objects
- `Map`: stores the grid size, starting money/lives, and is the parent for `PathNode`, `BuildSpot`, and `Wave` (via `related_name`s). Minimal `__str__` to show size.
- `PathNode` / `BuildSpot`: tile-level rows that clamp to a parent map; paths are ordered via `order_index` while build spots are a simple coordinate pair.
- `TowerType`: richly annotated with base stats, AoE settings, growth multipliers, and colors/shape attributes used for the renderer; `__str__` produces a cost-aware label.
- `TowerLevel`: unique per `(tower_type, level_number)`; defines damage/range/fire-rate/cost multipliers plus two AoE rings.
- `EnemyType`: base health, speed, bounty, and icon styling used by `main.js`.
- `Wave` / `WaveEnemy`: map-centric wave list with `WaveEnemy` entries that define count/spawn interval and tie to `EnemyType`.
- `Campaign` -> `CampaignStage` -> `StageWave` -> `StageWaveGroup`: hierarchical campaign builder. `CampaignStage` references a `Map`, can reuse `Wave`s from that map (`use_map_waves`/`waves_to_play`), has optional messages and overrides, and each `StageWaveGroup` pins to an `EnemyType` with spawn timing metadata.

## 6. Request / User Flow
- `/td-now/` renders `index.html`, which pulls `/td-now/api/levels/<map>` or `/td-now/api/campaigns/<id>/` depending on `map`/`campaign` query params; `main.js` drives the canvas game, Start Wave button, upgrade UI, and `CampaignEngine` wrapper that currently returns early (see Known Gaps).
- `/td-now/campaign-select/` lists campaigns and maps via `campaign_select.js`, letting users click through to `/td-now/play/` with `campaign`/`map` parameters or to the builders.
- `/td-now/play/` is the main game screen; `main.js` fetches JSON, builds the tower list, and manages in-browser state (money, lives, waves, towers, AoE effects, and an infinite-mode wave generator triggered by `?infinite=1`).
- `/td-now/builder/`: login-restricted page running `builder.js` that draws a grid canvas, tracks ordered `path` tiles and `buildSpots`, and calls `/td-now/api/maps/` (POST) or `/td-now/api/maps/<id>/` (PUT) when saving. `builder.js` resets nodes before saving and re-fetches `levels` for the load dropdown.
- `/td-now/campaign-builder/`: login-only editor where `campaign_builder.js` fetches `/td-now/api/levels/`, `/td-now/api/enemies/`, and `/td-now/api/campaigns/`, lets staff craft stages/waves/groups, and issues POST to `/td-now/api/campaigns/create/` or PUT to `/td-now/api/campaigns/<id>/update/` depending on the presence of `?id=`. The UI loops over stages/waves/groups to build the JSON payload.
- `/td-now/assets/`: login-only asset editor where `asset_editor.js` performs CRUD on towers and enemies via `/td-now/api/towers/`, `/td-now/api/towers/create/`, `/td-now/api/towers/<id>/`, and the equivalent enemy endpoints; each save includes `X-CSRFToken` from cookies.
- JSON endpoints (`levels_list`, `enemies_list`, `towers_list`, `level_detail`, `campaigns_list`, `campaign_detail`) are publicly readable and feed the JavaScript clients with tower/enemy metadata plus `waves`/`groups` definitions.

## 7. Templates and UI Surface Area
- Templates: `td_now/index.html`, `campaign_select.html`, `builder.html`, `campaign_builder.html`, `asset_editor.html`. They all extend `base_template.html`, include `td_now/style.css`, and append the appropriate JS bundle with a `cache_version` query string.
- Static assets: `style.css` defines the shared look, `main.js` contains the canvas game plus campaign/infinite logic, `builder.js` manages the canvas editor, `campaign_builder.js` constructs the DOM for nested stages/waves/groups, `asset_editor.js` renders editable rows for towers/enemies, `campaign_select.js` populates the selection panels.
- UI is entirely server-rendered + vanilla JS; the gameplay screen is canvas-heavy, while the builders and asset editor are DOM-heavy but still non-SPA—no React/HTMX, just small modules creating DOM nodes and fetching JSON.
- Shared partials: no partial templates specific to td_now; lookups happen in JS (e.g., `campaign_select.js` builds `<div class="row">` rows directly).

## 8. Admin / Staff Functionality
- Every model is registered in `td_now/admin.py` with list displays targeting the key attributes (map size & resources, tower stats, stage order, etc.).
- `TowerTypeAdmin` includes an inline `TowerLevelInline` so upgrades are edited on the same page.
- `WaveAdmin` nests `WaveEnemyInline`; `StageWaveAdmin` nests `StageWaveGroupInline`; `CampaignStageAdmin` nests `StageWaveInline`.
- Staff can seed levels via `python manage.py seed_td_now` to ensure default map/campaign/towers/enemies exist.

## 9. Forms, Validation, and Input Handling
- There are no Django `forms.py` or serializers inside `td_now`; validation happens manually in the view functions.
- `views.create_map` and `update_map` `json.loads` the request body, ensure `width`/`height` are positive, and rebuild `PathNode`/`BuildSpot` rows every save.
- Tower/enemy create/update views coerce the expected numeric fields (`cost`, `damage`, `hp`, etc.) and reject unknown JSON with `HttpResponseBadRequest` if parsing fails.
- Campaign creation/update enforces that referenced map or enemy IDs exist via `get_object_or_404`, always deletes existing stages before recreating them, and honors optional overrides like `startMoneyOverride`.
- Front-end editors append `X-CSRFToken` from cookies to each modifying request to satisfy Django CSRF protection.

## 10. Business Logic and Services
- `views.campaign_detail` builds a payload combining campaign defaults, stage overrides, and either custom `StageWave` groups or derived `Wave`s from the linked `Map` when `use_map_waves` is true.
- `update_map`/`create_map` normalize the `path` order and `build_spots` before saving to the database, always wiping and bulk-creating the related rows.
- `asset_editor.js` and `builder.js` handle the DOM state for editors, but the canonical logic lives in the view functions that enforce foreign-key integrity.
- `static/td_now/main.js` encapsulates the real-time simulation: `GameEngine` manages enemy spawns, `Tower` handles targeting/AoE, `generateInfiniteWave` fosters tonal infinite play, and `CampaignEngine` (currently unreachable) is meant to chain stages and surface overlays.
- `management/commands/seed_td_now.py` is the only scripted data population mechanism, ensuring default towers (`Gatling`, `Cannon`), enemies (`Grunt`, `Runner`, `Tank`, `Boss`), waves, and a “Training Wheels” campaign exist post-migrations.

## 11. Integrations and Cross-App Dependencies
- `STATZWeb/settings.py` includes `td_now.apps.TDNowConfig`; `STATZWeb/urls.py` exposes the app at `/td-now/` so all its routes are accessible from the main site.
- `scripts/inspect_campaigns.py` imports `td_now.models` to print campaign metadata, showing that management scripts rely on these models.
- The app has no dependencies on other local feature apps—only standard Django components plus the `td_now` models themselves.

## 12. URL Surface / API Surface
| Pattern | Purpose |
| --- | --- |
| `td-now/` | Game landing page (`index.html`, loads `main.js`). |
| `td-now/campaign-select/` | Campaign/map chooser that drives playback or editors. |
| `td-now/play/` | Canvas player template; `main.js` fetches the selected level/campaign. |
| `td-now/builder/` | Login-only map builder canvas. |
| `td-now/campaign-builder/` | Login-only campaign editor UI. |
| `td-now/assets/` | Login-only tower/enemy asset editor. |
| `td-now/api/levels/` | GET list of maps (id/name/size). |
| `td-now/api/levels/<map_id>/` | GET map detail: path, build spots, towers, enemies, waves. |
| `td-now/api/maps/` | POST to create a map (requires CSRF/login). |
| `td-now/api/maps/<map_id>/` | PUT/PATCH map metadata + nodes/spots (login + JSON). |
| `td-now/api/campaigns/` | GET list of campaigns. |
| `td-now/api/campaigns/<campaign_id>/` | GET full campaign (stages, waves, towers, enemies). |
| `td-now/api/campaigns/create/` | POST new campaign with stage/wave data (login). |
| `td-now/api/campaigns/<campaign_id>/update/` | PUT to replace a campaign’s stages (login). |
| `td-now/api/towers/` | GET tower list. |
| `td-now/api/towers/create/` | POST new tower (login). |
| `td-now/api/towers/<tower_id>/` | PUT/PATCH tower updates (login). |
| `td-now/api/enemies/` | GET enemy list. |
| `td-now/api/enemies/create/` | POST new enemy (login). |
| `td-now/api/enemies/<enemy_id>/` | PUT/PATCH enemy updates (login). |

## 13. Permissions / Security Considerations
- Editor views (`builder`, `campaign_builder`, `asset_editor`) and all mutation APIs are decorated with `@login_required`. The public-facing GETs (`levels_list`, `campaigns_list`, `level_detail`, `campaign_detail`, `towers_list`, `enemies_list`) are open.
- CSRF protection is enforced; every modifying endpoint uses `json.loads` and the front-end sends the `X-CSRFToken` cookie value.
- No object-level permissions are implemented: logged-in users can modify any tower/map/campaign. Review access if the app ever becomes multi-tenant.
- The canvased gameplay does not expose file uploads, but map/campaign editors can delete/recreate entire stages, so cross-app data integrity must be revalidated if other features reference `Map` records.

## 14. Background Processing / Scheduled Work
- No Celery tasks or cron jobs exist; all behavior is synchronous.
- `management/commands/seed_td_now.py` is the only script hooking the models for automated seeding.
- There are no signal receivers, asynchronous tasks, or exports tied to this app.

## 15. Testing Coverage
- No tests live in `td_now/` (no `tests.py`, `tests/`, or test-related modules).
- The app’s JavaScript is unchecked by Django’s test suite.
- Any future change should introduce targeted tests, especially around the JSON endpoints and builder/campaign creation logic.

## 16. Migrations / Schema Notes
- Seven migrations exist (`0001_initial` through `0007_enemytype_icon_color_enemytype_icon_hit_color_and_more`).
- Key schema notes: `Map` owns path/build nodes and waves; `TowerLevel` enforces `unique_together` on `(tower_type, level_number)`; `CampaignStage` stages maintain order via `order_index` and optionally override resources.
- Migrations show a history of pushing optional icon metadata and campaign stage messaging fields.

## 17. Known Gaps / Ambiguities
- `static/td_now/main.js` instantiates `new CampaignEngine(...)` but the subsequent `return;` prevents that engine from ever running, and the `CampaignEngine` class is declared **after** the IIFE closes, so campaign mode likely throws a `ReferenceError` before the class exists.
- `static/td_now/campaign_builder.js` defines `async function save()` twice; the second definition overrides the first, so the earlier POST-only version is unreachable and it is unclear whether `currentId` handling (create vs. update) works as intended.
- The builder template (`builder.html`) has mismatched `<div>` closing tags around the save/update buttons, which can trip DOM layouts if the surrounding structure is edited.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- Before renaming any model field, check how `main.js`, `builder.js`, and the campaign builder payloads reference that field by name (e.g., `startMoney`, `spawnInterval`, `iconElement`).
- Any change to JSON endpoints or `td_now/static/td_now/*` should be coordinated: the front-end assumes precise property names (case-sensitive) and the builder/editor scripts expect arrays of `groups`/`waves`.
- After editing data structures or serializers, run `python manage.py seed_td_now` to refresh the sample map/campaign so the UI has something playable.
- Review `campaign_builder.js` and `asset_editor.js` together when modifying their APIs; they build DOM nodes dynamically and will break silently when selectors or payload shapes drift.

## 19. Quick Reference
- Primary models: `Map`, `TowerType` (+`TowerLevel`), `EnemyType`, `Wave`/`WaveEnemy`, `Campaign` + `CampaignStage` → `StageWave` → `StageWaveGroup`.
- Main URLs: `/td-now/` (game), `/td-now/builder/`, `/td-now/campaign-builder/`, `/td-now/assets/`, `/td-now/api/*`.
- Key templates: `templates/td_now/index.html`, `campaign_select.html`, `builder.html`, `campaign_builder.html`, `asset_editor.html`.
- Key dependencies: hits `STATZWeb` for URL inclusion, uses Django auth decorators, and is referenced by `scripts/inspect_campaigns.py` for diagnostics.
- Risky files: `static/td_now/main.js` (game engine + campaign logic), `static/td_now/campaign_builder.js` (save semantics), `static/td_now/builder.js` (grid state serialization).


## CSS Architecture

This project does not use Tailwind in any form. The CSS refactor replaced all Tailwind with Bootstrap 5 and a custom three-file CSS architecture:

- `static/css/theme-vars.css` — CSS custom properties only (color tokens, brand vars, dark mode overrides via `body.dark`). Hex values live here. Do not put layout or component styles here.
- `static/css/app-core.css` — layout, structure, and all component/button/modal styles. References `var()` tokens from `theme-vars.css`. New component classes go here.
- `static/css/utilities.css` — utility and helper classes.

**Do not modify:** `static/css/tailwind-compat.css` or `static/css/base.css`.

**When encountering Tailwind classes in templates:** replace with Bootstrap 5 equivalents or named classes in `app-core.css`. Do not leave Tailwind utility classes in place.

**Button pattern:** `.btn-outline-brand` in `app-core.css` is the standard outlined brand button. Use `.btn-outline-brand.btn-tinted` for a pill-style variant with a light `#eff6ff` background (e.g. the reminders pop-out button in `contract_base.html`).
