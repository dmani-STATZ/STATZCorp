# AGENT.md — STATZCorp Project Notes

## Workflow Improvements

### IDIQ Parser Detection and Shadow-Schema Metadata (2026-04-15)

**Contract number regex:** `_RE_DLA_CONTRACT` uses `[A-Z0-9]{4}` for the trailing segment (was `\d{4}`) so alphanumeric suffixes like `SPE7M5-26-D-60JK` are matched.

**Detection (two independent gates — either triggers IDIQ):**
1. **Type-code gate:** Strip hyphens from the extracted contract number and check `position[8] == 'D'` (1-based: 9th character). For `SPE7M5-26-D-60JK` → bare `SPE7M526D60JK`[8] = `'D'`. This matches the DLA IDIQ naming convention where the segment after the year code is the contract type identifier.
2. **Text gate:** Document contains the phrase "Indefinite Delivery Contract" (via `_RE_IDIQ_TEXT_DETECT`).
Both gates call `contract_type = "IDIQ"` after `_apply_contract_number_rules`.

**Metadata extraction (IDIQ only):**
| Field | Exact source pattern |
|---|---|
| `idiq_max_value` | `Contract Maximum Value: $<amount>` |
| `idiq_min_guarantee` | `Guaranteed Contract Minimum Quantity: <qty>` |
| `idiq_term_months` | `_RE_IDIQ_TERM` captures `(one\|...\|N) (year\|month)[s] [period]` → `_term_to_months(qty, unit)` |

`_term_to_months(qty_str, unit)` accepts either a word (`"one"`, `"five"`) or digit string plus `"year"` or `"month"`. Examples: `"one", "year"` → 12; `"five", "year"` → 60; `"6", "month"` → 6.

Per-CLIN: `_extract_min_order_qty_map` scans up to 800 chars after each CLIN item-number marker for "Minimum Delivery Order Quantity". The result is stored in `ClinParseResult.min_order_qty_text`.

**Shadow Schema format** — packed into `QueueContract.description` by `ingest_parsed_award` when contract_type is IDIQ:

```
IDIQ_META|TERM:12|MAX:350000|MIN:19
```

All three segments are optional; only segments with extracted values are appended.  `start_processing` copies `queue_item.description` into `ProcessContract.description` so the metadata survives into the edit phase.

For IDIQ CLINs, `QueueClin.nsn_description` is set to the min delivery order quantity string (e.g. "5 EA") rather than the item nomenclature, allowing the IDIQ processing page to initialise the min-order-qty inputs from parsed data.

**Routing:** `start_processing` checks `queue_item.contract_type == 'IDIQ'` and returns a `redirect_url` pointing to `processing:idiq_processing_edit` instead of the standard `process_contract_edit` view. The queue JS reads `data.redirect_url` (new field) if present before falling back to the default edit URL.

**IDIQ Processing Page (`idiq_processing_edit`):** Unpacks the shadow-schema string from `process_contract.description`, displays Term / Max Value / Min Guarantee editable header fields (term years → months JS conversion on-the-fly), and a CLIN table with NSN Match, Supplier Match, and Min Order Qty inputs.

**Finalization (`finalize_idiq_contract`):** Validates all CLINs are matched, creates one `IdiqContract` and one `IdiqContractDetails` per CLIN, then deletes the `ProcessContract` and `QueueContract` records in a single `transaction.atomic` block.

**Schema additions:**
- `QueueContract.description` (TextField, null=True) — migration `processing/0017`
- `IdiqContract.max_value`, `IdiqContract.min_guarantee` (DecimalField, null=True) — migration `contracts/0038`
- `IdiqContractDetails.min_order_qty` (CharField max_length=50, null=True) — same migration

### Queue merge — match orphaned contract number (2026-04-15)

Orphaned `QueueContract` rows (`contract_number` empty) can be reconciled from the queue via **Match Contract** (`processing:match_contract_number`, POST `target_contract_number`). The handler runs in `transaction.atomic()` and locks the orphan and any merge target with `select_for_update()` so two analysts cannot merge the same rows inconsistently.

- **Merge into existing queue row (true merge):** If another `QueueContract` already has that contract number (same `company`), header fields are coalesced onto the target with **orphan wins** when the orphan has a value: `buyer`, `award_date`, `due_date`, `contract_value`, `contract_type`, `idiq_number`, `contractor_name`, `contractor_cage` (target keeps its value when the orphan’s field is null/blank). All `QueueClin` rows still move to the target; on CLIN line-number match (after trim), orphan CLIN fields overwrite the target CLIN (orphan wins), then the orphan CLIN is deleted; otherwise the CLIN’s `contract_queue` FK is repointed. The target then gets `pdf_parse_status='success'`, `pdf_parsed_at` from the orphan, and `pdf_parse_notes` built from both records’ notes plus the line *Data merged from orphaned PDF record.* The orphan `QueueContract` is deleted.
- **No queue duplicate:** The orphan’s `contract_number` is set to the entered value, `pdf_parse_status` / `pdf_parse_notes` are updated the same way, and the row is kept.

Blocked cases: row already has a contract number, item is `is_being_processed`, or a `ProcessContract` still references the queue id.

## UI Improvements

### CSS Refactor Phase 1 — theme-vars.css (2026-04-16)

Created `static/css/theme-vars.css` as the single source of truth for all color tokens. Merged contents from:
- `:root` block from `base.css` (brand tokens: `--company-primary`, `--company-secondary`, `--company-danger`, `--main-font`, `--header-height`)
- `semantic-light.css` (all light-mode semantic variables, selector changed from `body.light` → `:root, body`)
- `semantic-dark.css` (all dark-mode semantic variables, `body.dark` selector preserved)

**Bug fixes included:**
- `--secondary` was referencing `--company-secondary` (`#e5e7eb`) making secondary buttons nearly invisible on light backgrounds. Fixed to hardcoded `#6b7280` in both light and dark modes.
- `--danger` in light mode wired to `var(--company-danger)` brand token for consistency (was hardcoded `#dc2626`).
- `--danger-hover` in light mode adjusted from `#b91c1c` → `#991b1b` to maintain visual contrast with the new base danger color.
- `--secondary-hover` in light mode adjusted from `#6b7280` → `#4b5563` so hover state is visually distinct from base state.
- Dead CSS fallback values removed from `--primary`, `--secondary`, and `--danger` (fallbacks never fired because brand tokens are always defined in `:root`).
- Applied style declarations (`background-color`, `color`) removed from theme variable blocks — these will be handled by `app-core.css` using `var()` references.

**Files deleted:** `semantic-light.css`, `semantic-dark.css` (fully consumed by `theme-vars.css`).

### CSS Refactor Phase 2 — app-core.css + HTML Link Update (2026-04-16)

Created `static/css/app-core.css` consolidating all layout, structural, and component styles. Merged contents from:
- `base.css` (everything except `:root` block)
- `light-mode.css` (structural rules only, color assignments replaced with `var()` references)
- `dark-mode.css` (all `body.dark` overrides, hex colors converted to `var()` references)
- `components.css` (all rules)
- `theme.css` (all rules, already var-based)

**Duplicate conflicts resolved:**
1. **Button class war:** `.btn-brand` deleted, triple `.btn-primary` consolidated to single `theme.css` version using `var(--primary)`. Old `base.css` `.btn-secondary` (hardcoded grays) replaced with `theme.css` version using `var(--secondary)`.
2. **Layout helpers:** Deduplicated `.row`, `.row-between`, `.label`, `.text-muted`, `.card`, `.card-padded` — single copy of each, `.card` keeps the border from `base.css`.
3. **`.section-header`:** Five definitions across three files collapsed to one using `var(--text-strong)`, `var(--surface-muted-bg)`, `var(--border-muted)`, `var(--primary)`. No `body.dark` override needed.
4. **`.form-label`:** Two definitions collapsed to one using `var(--text-muted)`. No `body.dark` override needed.

**Dead code removed:**
- All `composes:` directives (CSS Modules syntax, non-functional in browser CSS)
- `.nsn-modal*` empty stubs (HTML already applies `.modal-base` class directly)
- Redundant `body.dark` overrides now handled by CSS variables

**`/* NEEDS VAR */` flags placed on:**
- `body.dark th` background (`#111827` — no semantic token for dark table header bg)
- `body.dark a:not([class*="text-"])` link color (`#93c5fd` — needs lighter-than-primary token)
- `body.dark .hover\:bg-*:hover` (`#4b5563` — needs hover-above-muted token)
- `.protal-card-text` color (`#3966c9` — typo class with accent color, no matching token)

**Files deleted:** `base.css`, `light-mode.css`, `dark-mode.css`, `components.css`, `theme.css`

**HTML updated:** `templates/base_template.html` `<link>` tags replaced with new load order: `theme-vars.css` → `app-core.css` → `utilities.css`. Old `tailwind-compat.css` reference updated to `utilities.css` (copy of compat utilities).

### Global Width Expansion, Status Key Pairs & Action Button Refactor (2026-04-15)

Updated `processing/templates/processing/process_contract_form.html` for 1920×1080 optimisation:

- **Global width**: Main content container changed from `container mx-auto` to `w-[90%] mx-auto` to utilise more screen real estate.
- **Processing Status key**: Refactored the color-swatch legend from loose `<span>` elements to paired `<div class="flex items-center gap-2 mr-4">` wrappers. Parent container changed to `flex flex-wrap` so swatch+label pairs always wrap together rather than splitting across lines.
- **Contract Action buttons**: Removed hardcoded `w-64` from all three buttons ("Update Value and Plan Gross", "Cancel and Return to Queue", "Submit Contract and Create Email"). Applied `w-full whitespace-nowrap` to each button and changed the wrapper to `flex flex-col gap-3 w-full` so all buttons fill the sidebar at uniform width. All `id`, `onclick`, and `data-*` attributes preserved unchanged.

### IDIQ and Buyer Match Buttons — Bootstrap Input Groups (2026-04-15)

Migrated the **IDIQ Contract** (`cont_idiq_contract_number`) and **Buyer** (`cont_buyer_text`) field wrappers in `processing/templates/processing/process_contract_form.html` from `<div class="row gap-2">` to `<div class="input-group input-group-sm">`.

- Input fields updated to `form-control` class so Bootstrap 5 Input Group sizing works correctly.
- Match buttons updated to `btn btn-primary btn-sm` to render inline with the input.
- Remove button (IDIQ only) updated to `btn btn-danger btn-sm`.
- Status SVG icons wrapped in `<span class="input-group-text border-0 bg-transparent p-1">` so they sit flush to the right inside the group.
- All `data-action`, `data-idiq`, `data-buyer`, and `onclick` attributes preserved unchanged — these are wired to `static/processing/js/idiq_modal.js` and `static/processing/js/buyer_modal.js`.

### CLIN-Level Match/ReCalc Input Groups & Toggle Icons (2026-04-15)

Migrated CLIN-level field wrappers in `processing/templates/processing/process_contract_form.html` to Bootstrap 5 Input Groups:

- **NSN Section**: `nsn` input + "Match" button + status SVG now wrapped in `.input-group.input-group-sm`. Input uses `form-control`, button uses `btn btn-primary btn-sm`, SVG wrapped in `<span class="input-group-text border-0 bg-transparent p-1">`.
- **Supplier Section**: Same treatment as NSN — `supplier` input + "Match" button + status SVG in `.input-group.input-group-sm`.
- **Total Value Section**: `item_value` input + "ReCalc" button in `.input-group.input-group-sm`. Button uses `btn btn-success btn-sm`.
- **Quote Total Section**: `quote_value` input + "ReCalc" button in `.input-group.input-group-sm`. Button uses `btn btn-success btn-sm`.
- All `data-action`, `data-id`, `data-clin-id`, and `onclick` attributes preserved unchanged — these drive AJAX match and recalc logic.

**Toggle button** (`data-action="toggle-clin"`) updated to `btn btn-sm btn-outline-primary` for a compact footprint.

**`toggleClinDetails(index)`** updated with stateful icons:
- Expanded state → Up Chevron SVG + "Collapse" label.
- Collapsed state → Down Chevron SVG + "Expand" label.
- Icon size reduced to `h-4 w-4` to match the smaller button.

**CLIN footer action buttons** now include text labels for clarity:
- Save button (green): disk icon + "Save" text, white fill on icon.
- Delete button (red): trash icon + "Delete" text.

### Sidebar Button Standardization, CLIN Density & Expansion Persistence (2026-04-15)

Updated `processing/templates/processing/process_contract_form.html`:

- **Sidebar button standardization**: All three Contract Action buttons ("Update Value and Plan Gross", "Cancel and Return to Queue", "Submit Contract and Create Email") now use a uniform class set anchored to Bootstrap flex utilities (`btn w-full d-flex align-items-center justify-content-center gap-2 py-2`). Removed the erroneous `.row` class from the "Update Value" button; color-variant classes (`btn-save`, `btn-caution`, `bg-green-400`) are retained.
- **CLIN vertical density**: Reduced `mb-4` → `mb-2` on all CLIN details content grids (Item Line, NSN/Due Date, CLIN Section, Supplier, Payment/Quote). Changed `mb-4` → `my-2` on the two `<hr />` divider containers. Reduced Save/Delete button container from `mt-4` → `mt-2`.
- **CLIN expansion persistence via `localStorage`**: `toggleClinDetails(index)` now calls `localStorage.setItem('expandedClinIndex', index)` on expand and `localStorage.removeItem('expandedClinIndex')` on collapse. The `DOMContentLoaded` CLIN listener now reads `expandedClinIndex` on load, calls `toggleClinDetails` for the saved index, and smooth-scrolls the toggle button into view.

### Sidebar Menu Density — 1080p Layout Tightening (2026-04-16)

Updated `templates/base_template.html`:

- **Sidebar menu density increased for 1080p displays**: Reduced list top-margin from `mt-10` → `mt-4`, item spacing from `space-y-1` → `space-y-0`, and per-item padding from `py-3 px-6` → `py-1.5 ps-4`. Container padding changed from `px-4 pb-8` → `ps-2 pe-0 pb-4`. Logo margin reduced from `2rem` to `1.5rem 2rem`.
- **Submenu alignment shifted from percentage-based (`100%`) to fixed-offset (`180px`)** to ensure connectivity with menu labels regardless of logo slant geometry. The invisible mouse-bridge (`::before`) widened from `8px` to `40px` to prevent submenu dismissal during diagonal cursor movement.

### Sidebar Menu Horizontal Offset & Vertical Rhythm Correction (2026-04-16)

Updated `templates/base_template.html`:

- **Horizontal offset corrected**: Menu labels shifted toward the left edge. Container padding reduced from `ps-2` → `ps-1`; per-item padding changed from `py-1.5 ps-4` → `py-2 ps-1`.
- **Vertical density relaxed**: List spacing restored from `space-y-0` → `space-y-2` and top margin from `mt-4` → `mt-6` to restore legible vertical rhythm on 1080p displays.
- **Submenu anchor adjusted to `140px`** (down from `180px`) to maintain proximity to labels after the leftward text shift. Mouse-bridge width reduced to `30px` to match the tighter offset.
