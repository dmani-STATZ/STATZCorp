# AGENTS.md — `contracts` App
> **Cross-app work?** Read `PROJECT_CONTEXT.md` first — it maps every app's ownership, shared infrastructure, and cross-boundary change rules for all 13 apps.

## 1. Purpose of This File

This file defines safe-edit guidance for AI coding agents and future developers working inside the `contracts` Django app. Read `contracts/CONTEXT.md` first for feature-level orientation. This file focuses on execution safety: what to read before editing, what breaks together, and where the real risk is.

---

## 2. App Scope

**Owns:**
- Canonical data for `Contract`, `Clin`, `Company`, `GovAction`, `FolderTracking`, `ClinSplit`, `Expedite`, `Note`, `Reminder`, `PaymentHistory`, `AcknowledgementLetter`, `ClinAcknowledgment`, `ClinShipment`, `IdiqContract`
- All lookup/code tables: `ContractStatus`, `Buyer`, `ContractType`, `ClinType`, `SalesClass`, `SpecialPaymentTerms`, `CanceledReason`
- The multi-tenant `Company` model and its branding/SharePoint configuration
- The full contract lifecycle UI: dashboard, contract management page, CLIN detail, folder tracking, finance audit, contract log, IDIQ pages
- All note, reminder, and payment history tracking for contracts and CLINs
- Acknowledgement letter generation and supplier management UI (delegates model reads to `suppliers` app)

**Does not own:**
- `Supplier`, `Contact`, `Certification`, `Classification` data — owned by `suppliers` app; `contracts` only reads and displays them
- `Nsn` (National Stock Number) — owned by `products` app; `Clin` holds an FK to it
- `SequenceNumber` — owned by `processing` app; used for PO/TAB number defaults
- `UserCompanyMembership` — owned by `users` app; `CompanyForm` syncs to it but does not define it
- The audit transaction trail — written by `transactions` app signals on `Contract`/`Clin` saves and on `ClinShipment` when **`ClinShipment.pod_date`** changes. **`Clin.pod_date`** is an optional CLIN-level `DateField` (null/blank, no late flag), distinct from shipment-level POD. `Clin.ship_date` and `Clin.ship_qty` are tracked in `transactions/signals.py`; do not manually create `Transaction` rows when saving those fields — normal `Clin.save()` (including `save(update_fields=[...])` from views such as `complete_clin_shipping`) is enough for the audit trail.

**Role:** This is the core domain app of the project. Nearly every other app depends on or integrates with it.

### Navigation / redirect rules

- **Company switcher on contract pages:** When on `/contracts/<pk>/` (or sub-pages such as `/close/`, `/cancel/`, `/review/`, `/detail/`, `/mark-reviewed/`) or on `/contracts/finance-audit/<pk>/`, switching the active company redirects to `contracts:contracts_dashboard` (main lifecycle dashboard at `/contracts/`), not back to the current URL. This is intentional — contract PKs are company-scoped and cannot be reused cross-company. Do not revert this redirect in `users.views.switch_company` without adding a cross-company existence check first.

**ClinSplit (2026-04):** `ClinSplit` rows cascade-delete with their parent `Clin`. Contract-level split totals are computed aggregates (`Contract.total_split_value` / `total_split_paid`), not stored fields. **Do not** add a stored split total back to the `Contract` model.
- **ClinSplit.percentage:** Nullable decimal. Do NOT treat it as a derived field or compute it from `split_value`. It is user-entered. The `recalc_splits` view is the only place `split_value` is computed from `percentage` — do not replicate this logic elsewhere.
- **`recalc_splits` save behavior:** The view uses `.save(update_fields=['split_value', 'modified_at'])` on each `ClinSplit`, which keeps transactions signal behavior intact for `split_value`. The bulk `.update()` used by `update_clin_split` when `apply_to_all_clins=True` intentionally bypasses signals because it only propagates `percentage` and that field is not transaction-tracked.
- **`get_item` template filter:** `finance_audit.html` relies on `get_item` in `contracts/templatetags/contract_tags.py` for `clin_splits_by_company` and `company_percentages`. Do not remove it.
- **`log_split_paid` endpoint:** POST `contracts/<contract_pk>/splits/log-paid/`. Accepts `{company_name, total_paid}`. Distributes `total_paid` proportionally across `ClinSplit` rows for that company using `split_value` as weight. Last row absorbs rounding remainder. NULL `split_value` == 0 (excluded from denominator). If all weights are zero, distributes equally. Saves via `split.save(update_fields=['split_paid', 'modified_at'])`. Returns per-CLIN breakdown, discrepancy flag, and `discrepancy_amount`. Does NOT touch `split_value`.

**Removed 2026-04-30:** `ContractCreateView`, `ContractUpdateView`, `ContractForm`, `contract_form.html`, and `dd1155_views.py` have been deleted. Contract creation flows through the **Processing** app finalization workflow. Do not recreate these files or URL routes (`/contracts/create/`, `/contracts/<pk>/update/`, dd1155 extract/export URLs, `dd1155_test`).

**Deprecation note:** `api_add_note` (in `contracts/views/note_views.py`) is deprecated. It redirects instead of returning JSON, lacks active-company scoping on note creation, and has been superseded by `add_note` for all AJAX flows. Debug `print` statements have been removed; the URL is retained temporarily for bookmarked links only. Do not add new callers. Planned removal: next cleanup pass.

**Recent (2026-04-24):** Fixed note modal double-POST (removed duplicate `extra_js` block nesting in `contract_base.html`); removed Reminder Details from the note modal; added default Reminder Title for contract/CLIN notes; `reminder_text` is copied from the note body on save. Toast notifications: replaced `showSuccessMessage`/`showErrorMessage` in `note_modal.js` with `window.notify()`; moved `messages.success()` in `add_note` and `delete_note` to the non-AJAX branch only; static Django message banners now auto-dismiss after 5 seconds. CLIN detail page (`clin_detail.html`) redesigned with a fixed left sidebar + Bootstrap ScrollSpy, color-coded section cards, and always-visible Financials section; styles live in `components.css` under `/* === CLIN Detail Page === */`. `contract_base.html` gained `{% block body_class %}{% endblock %}` on the outer wrapper to support page-level layout overrides. See section 5 "CLIN detail page layout" below for the change-together file list. `contract_review.html` uses the same `.clin-detail-layout` / `.clin-detail-page` CSS classes as `clin_detail.html` for the fixed sidebar escape hatch. Review page sidebar id is `#review-page-nav`. All review page component classes are prefixed `.review-*` and live in `components.css` under `/* === Contract Review Page === */`.

---

## 3. Read This Before Editing

### Before changing models
- **`ContractStatusHistory`:** append-only audit of `Contract.status` changes. Do not assign `Contract.status` in application code without creating a matching `ContractStatusHistory` row in the **same** `transaction.atomic()` block as the save. Close, cancel, and re-open views are the primary mutators; ad-hoc status flips elsewhere are a footgun. **Phase 2 (not started):** legacy fields `closed_by`, `cancelled_by`, `date_closed`, `date_canceled`, and `canceled_reason` are scheduled for removal after production verification — do not delete them in unrelated tasks.
- `contracts/models.py` — understand `on_delete` choices; `Company` uses `PROTECT` and `Nsn` uses `PROTECT`, meaning deletion will hard-fail if children exist
- `contracts/migrations/` — check the latest migration before adding fields; 37+ migrations exist with compound indexes
- `transactions` app signals — signals in `transactions/` fire on `Contract`, `Clin`, `ClinShipment` (tracked `pod_date`), and `Supplier` post/pre_save; renaming tracked fields will silently break the audit trail
- `processing/models.py` — `QueueContract` and `QueueClin` mirror Contract/Clin fields; a schema change may require parallel updates there
- `sales/` views/services that reference contract fields (e.g. SQL view DDL under `sales/sql/` joining `contracts_clin` / `contracts_contract` / `contracts_nsn`)

### Before changing views
- `contracts/views/mixins.py` — `ActiveCompanyQuerysetMixin` must remain on every queryset-based view; removing it leaks cross-tenant data
- `contracts/views/contract_views.py` — central hub; `ContractManagementView` builds a large context (CLINs, notes, splits, GovActions, folder tracking); adding keys here affects the main template
- `contracts/views/gov_action_views.py` — the helper `_gov_action_to_json()` is the single source of truth for the JSON shape of Gov Action AJAX responses. Both `gov_action_create` and `gov_action_update` must use it. Do not add fields to one endpoint without adding them to the helper.
- `contracts/views/payment_history_views.py` — the `delete_payment_history_entry` and `update_payment_history_entry` views recalculate and write back totals to the parent model using `_sync_entity_total_after_history_change` (same field-write logic as the POST handler). If you add new payment types or entity types to PaymentHistory in the future, update the POST handler AND both delete/update handlers (or extend `_sync_entity_total_after_history_change`).
- `contracts/views/finance_views.py` — `payment_activity_rollup` in `FinanceAuditView.get_context_data` returns ALL PaymentHistory entries for the contract and CLINs (no `payment_info` filter). Each dict includes `entity_type`, `entity_id`, `payment_type`, `current_value`, and `payment_date`. If you add fields to this dict, also update the `finance_audit.html` Payment Activity card template that renders it. Also: `Clin.adjusted_gross` now includes ALL finance lines (CLIN-level and partial-level). The inline recalc in `split_views.py` `recalc_splits` was updated to match. If you add finance line filtering anywhere that uses `partial__isnull=True` to scope adj gross calculations, you are reintroducing the old inconsistency — do not do this.
- **`Clin.adjusted_gross` formula (updated 2026-06-03):** Income side uses `COALESCE(wawf_payment, item_value)` — if `wawf_payment` is set and non-zero (government has paid, including any interest), use it as realized income. Fall back to `item_value` when `wawf_payment` is null or zero (pre-payment projection). Cost side uses `COALESCE(paid_amount, quote_value)` — `paid_amount` is the "official" number once populated and non-zero. Finance costs (all `ContractFinanceLine.amount_billed` for the CLIN, both CLIN-level and partial-scoped) are subtracted last. Do **not** add a stored field for this — it is and must remain a computed `@property`. The async refresh endpoints (`finance_audit_clin_api`, `finance_audit_summary_api`) and the page-load template all read `clin.adjusted_gross` directly; the `split_views.py` inline recalc must be kept manually in sync.
- **`Contract.adjusted_gross` (updated 2026-05-26):** Formula is now: `SUM(Clin.adjusted_gross) - packaging_deduction - charges_deduction` where `packaging_deduction = COALESCE(amount_paid, quote_amount, 0)` and `charges_deduction = SUM(COALESCE(charge.billed_paid_amount, charge.estimated_amount))` across all `ContractLevelCharge` rows for the contract. The full packaging cost is deducted — not just the variance. If `amount_paid` is set and non-zero, use it. If not, fall back to `quote_amount`. If neither exists, deduction is zero. `plan_gross` does NOT drive contract adj gross. Finance costs are already inside `Clin.adjusted_gross` — do not subtract `finance_costs_total` at the contract level. `FinanceAuditView.get_context_data()` and `finance_audit_summary_api()` must stay in sync — both now have a `charges_deduction` block that must match this logic exactly. Do **not** add a stored `adjusted_gross` field on `Contract` — it is and must remain a computed `@property`.
- `contracts/urls.py` — ~90 named URL patterns; reversals exist in templates throughout the project

### Before changing forms
- `contracts/forms.py` — `ClinForm.clean()` auto-calculates `item_value` and `quote_value`; disrupting this silently zeros out financial values
- `BaseFormMixin` — all forms inherit CSS widget styling from here; changes affect every form in the app
- `CompanyForm` — logo validation uses PIL (Pillow); PIL import is guarded, so if Pillow is missing it degrades silently

### Before changing templates
- **Finance Audit — Payment Activity panel:** The right-hand **Payment Activity** card lists contract- and CLIN-level `PaymentHistory` rows (same `ContentType` OR filter as before). `payment_info` is optional and is **not** used to filter the list. Pagination is server-rendered via `?pa_page=N` (50 per page); context keys are `payment_activity_rollup`, `payment_activity_page`, and `payment_activity_total`.
- **Finance lines visibility:** `ContractFinanceLine`, `FinanceLinePayment`, and `Clin` finance-line aggregates (`finance_lines`, `adjusted_gross`, etc.) must **never** be surfaced in contract management templates, CLIN detail templates, **processing** app templates, or any template outside `contracts/templates/contracts/finance_audit.html` and templates it `{% include %}s`. Admin and backend-only use are fine.
- **Finance line API endpoints** (add, list-by-CLIN, log-payment, list-payments, delete, plus partial-shipment list/add and partial add/auto-calc) live in `contracts/views/finance_line_views.py`. They only accept CLIN-scoped and finance-line–scoped identifiers; there is no contract-level finance-line aggregate endpoint. Do not expose finance line JSON or UI outside the finance audit page.
- **Finance Audit CLIN vs partial finance lines:** When querying finance lines for the CLIN-level Finance pill or `get_finance_lines`, always filter `partial__isnull=True`. Never show partial-scoped finance lines in the CLIN accordion. When querying for a partial Finance pill or partial APIs, always filter `partial=<that ClinShipment>`. `refreshFinanceLinesForClin()` refreshes CLIN-level lines only; `refreshPartialFinanceLines()` refreshes partial-level lines only — never call them interchangeably. The Add Partial modal reloads the page on success (v1); do not rely on dynamic insertion of new partial rows in JS.
- **Payment history for partials — CLIN rollup (Slice 2B/2C):** For `payment_history_api` POST/DELETE/PATCH (via `update_payment_history_entry`) with `entity_type='clinshipment'` and types `partial_wawf_payment` / `partial_paid_amount`, the view updates the shipment column/ledger, then calls **`_recompute_clin_payment_rollup(clin, user)`** in `shipment_views.py` — the **single writer** of converted-CLIN `paid_amount` / `wawf_payment` (`SUM` of shipment stored columns). Never write `clin.paid_amount` / `clin.wawf_payment` directly from shipment paths; never recreate synthetic `shipment-ph-*` CLIN `PaymentHistory` rows. `add_partial_shipment` uses the same helper after creating shipment ledger rows. **`clin.paid_amount` / `clin.wawf_payment` are NOT in `transactions.signals.TRACKED`** — do not add them (derived rollups for converted CLINs). On Finance Audit, **all** CLIN Paid/Customer Pay cells are read-only; money is entered on shipment ledgers only (Slice 2C). Server POST still rejects direct-on-CLIN paid/customer-pay when `clin.shipments.exists()`. `PATCH /contracts/api/payment-history/<id>/update/` edits ledger rows in place (popup **Edit**). For `partial_item_value` / `partial_quote_value`, no CLIN rollup.
- **Data migrations vs hand-run TSQL (standing rule):** Prefer a documented hand-run TSQL script (in `CONTEXT.md` / release notes, executed by the developer against the database) for bulk data conversions, backfills, and cleanups. Use a Django **data migration** only when the change must be applied atomically with the code deploy — when running before or after deploy would break the system. Default to TSQL; data migration only for that break-the-system case. Examples: Slice 2A unit-price backfill (TSQL), Slice 2B synthetic `shipment-ph-*` cleanup (TSQL Step 0b, after code deploy).
- **Payment type scope rules:** `partial_*` payment types are valid only for `clinshipment` entities. Do not use them for `contract` or `clin` entities.
- **ContractFinanceLine hard deletes** are allowed from the Finance Audit page only (DELETE `/contracts/api/finance-lines/<id>/delete/`). `FinanceLinePayment` rows are deleted via CASCADE when the parent line is deleted — never delete payment rows directly in application code.
- **Finance Audit async refresh endpoints** (`finance_audit_summary_api` and `finance_audit_clin_api` in `contracts/views/finance_views.py`): These lightweight endpoints recompute aggregates on-demand without reloading the page. `finance_audit_summary_api(request, contract_id)` returns contract-level aggregates (finance_costs_total, adj_gross_contract, clin_totals, contract_value_delta, contract_value_balanced, payment_activity_total). `finance_audit_clin_api(request, contract_id, clin_id)` returns single-CLIN data (quote_value, paid_amount, item_value, wawf_payment, adjusted_gross, shipment metrics). **CRITICAL sync requirement:** Both endpoints recompute the exact same aggregates as `FinanceAuditView.get_context_data()`. If you change the aggregation logic in `get_context_data()`, you **must** update both endpoints with the same logic. The JavaScript calls (`refreshContractSummary()` and `refreshClinRow(clinId)`) wire into payment history updates, finance line add/delete/pay operations, and payment value changes. These calls are debounced by 200ms to avoid cascading rapid-fire requests.
- **Finance Audit direct CLIN values (Slice 1, 2026-05-26):** `quote_value`, `unit_price`, and `price_per_unit` were added to `transactions/signals.py` `TRACKED` and the `Clin` pre_save snapshot; `item_value` was already tracked. `transaction_edit_field` now has a second model-specific special-case alongside `ClinShipment.pod_date` -> `_sync_clin_ship_fields`: editing `Clin.item_value` / `quote_value` reverse-derives and separately saves `unit_price` / `price_per_unit`. Keep the separate `save()` so the per-unit change gets its own `Transaction` row. Never collapse the two saves into one, and never recompute `item_value` / `quote_value` from the rounded per-unit price. Finance Audit `item_value` / `quote_value` cells open the Transactions edit modal, not the PaymentHistory popup. `paid_amount` / `wawf_payment` cell routing is unchanged.
- **Forward derivation (Slice A, 2026-05-27):** When `transaction_edit_field` saves `order_qty`, `unit_price`, or `price_per_unit` on a `Clin`, it calls `recompute_clin_derived_values(clin, user)` from `contracts/services/clin_compute.py` and includes the results in the response as `derived_updates`. Do NOT call this function from signals — it is view-layer logic only. Do NOT touch shipment rows from this function. `Clin.ship_qty` is read-only on the CLIN detail page when `clin.shipments.exists()` — enforced in the template via `clin_has_shipments` context flag from `ClinDetailView`.
- **`clin_ship_qty_api` (GET `/contracts/api/clin/<id>/ship-qty/`):** Returns `ship_qty` (float) and `has_shipments` (bool) for a CLIN. Intentionally minimal — do not add other fields here. Used only by `refreshClinShipQty()` on `clin_detail.html`. Company-scoped.
- **`get_clin_details` (`contracts/views/gov_action_views.py`):** Returns `has_shipments: bool` (from shipment count aggregate). The contract management CLIN card JS rebuild and SSR both use this to lock `ship_qty` to read-only when True. Do not add `item_value` or `quote_value` to the CLIN card on the contract management page — those fields belong on Finance Audit / CLIN detail.
- **`refreshClinShipQty()`** must be called (defensively via `typeof refreshClinShipQty === 'function'`) from `clin_shipments.js` after every shipment create, update, and delete success path.
- **Finance Audit direct Plan Gross (Slice 1b, 2026-05-26):** `plan_gross` was added to `transactions/signals.py` `TRACKED` and the `Contract` pre_save snapshot. It is the contract-level twin of the CLIN value facts converted in Slice 1. The Finance Audit Plan Gross cell opens the Transactions edit modal using the Contract content type, not the PaymentHistory popup. The Plan Gross row's `bi-arrow-up` icon was replaced with inline SVG per the Finance Audit no-`bi` rule. **Future cleanup:** if Bootstrap Icon markup reappears on the remaining Finance Audit summary rows (Contract Value, Finance Costs, Packaging Variance, Adj Gross), convert those rows to inline SVG in a dedicated pass.
- Check for `{% include %}` partials: `notes_list.html`, `payment_history_popup.html`, `clin_shipments.html` are included in multiple parent templates. The old `partials/contract_splits.html` is a comment-only stub; split UI lives on `clin_detail.html` and read-only rollups on contract pages.
- **`payment_history_popup.html` — Bootstrap 5 only, no Tailwind:** This file previously used Tailwind color/layout classes that broke dark mode. It has been converted to Bootstrap 5 equivalents. Do not re-introduce Tailwind color classes (`bg-white`, `text-gray-*`, `border-gray-*`, etc.) into this file. All theming must use Bootstrap utility classes that respond to `[data-bs-theme="dark"]` automatically.
- **`finance_audit.html` — Bootstrap Icons do not load on this page.**
  Never use `<i class="bi bi-*">` anywhere in `finance_audit.html` or in any
  template fragment rendered exclusively on the Finance Audit page (e.g.
  partials included only via `{% include %}` from `finance_audit.html`).
  Always use inline SVG for icons on this page. The Bootstrap Icons font/CSS
  is not included in the Finance Audit page's stylesheet chain. This omission
  is intentional; do not add the Bootstrap Icons stylesheet to fix it. This
  rule has caused multiple regressions when violated. No exceptions.
- **`clin_shipments.html` table layout:** In `mode="form"`, the data columns are Ship Date, Quantity, UOM, Comments, Quote Value, Paid, Item Value, Customer Pay, POD Date, then Actions (10 columns before Actions). In read-only/detail mode there are nine data columns (no Actions). Empty-state and footer `colspan` values must stay aligned with the column count. `ClinShipment.pod_date` is transaction-tracked; POD is edited via `openTransactionsEditModal` on CLIN detail (`window.clinShipmentContentTypeId`). The shipment audit (ⓘ) button is only rendered for server-rendered existing rows. The `#complete-shipping-row` footer action is only for form mode when fully shipped (`total_shipped == order_qty`); its visibility is toggled by `updateTotalShipQty()` in `clin_shipments.js` using `data-order-qty` on the `.section` wrapper (keep that attribute in sync if the partial changes).
- **`add_partial_modal.js`:** Must work on any page that includes `add_partial_modal.html`. The modal supports a CLIN selector mode when `window.financeClinList` is defined (Finance Audit context). In this mode the CLIN selector drives `#addPartialClinId`, UOM population, and auto-calc. When opened from a single-CLIN context (CLIN detail), selector is hidden and CLIN id comes from `data-clin-id` on the trigger button as before. The `name` field is always present in the modal; value is passed in the POST body to `add_partial_shipment`. Shipment Quote Value and Item Value are **read-only derived** (`readonly` inputs); auto-calc always writes them from QTY. Do **not** reintroduce editable quote/item inputs or the removed `data-manually-edited` override pattern. Page-specific behavior after save (if ever needed) should use a page-level listener on the `#addPartialModal` `hidden.bs.modal` event.
- **Finance Audit shipment values (Slice 2A, 2026-05-27):** Partial Quote/Item cells are static (`data-derived-field`); Paid / Customer Pay use `partial-value-cell` + `payment_history_popup.html` (add, **edit**, delete). New fallback: `POST /contracts/api/clin/<clin_id>/set-unit-prices/` (`clin_set_unit_prices` in `finance_line_views.py`) for CLINs with NULL `unit_price`/`price_per_unit`; saves via `.save(update_fields=...)` so Transactions fire. Does not retroactively update existing shipments' stored quote/item columns.
- **Finance Audit inline workbench (Slice 2C, 2026-05-27):** Header **Add Shipment / Add Finance Line / Log Payment** buttons are retired. Each CLIN row has **+ Shipment** (logistics-only modal; money fields hidden when `window.FINANCE_AUDIT_CONTRACT_ID` is set) and **+ cost** (CLIN-level). Each shipment row has **+ cost** (shipment-scoped). Triggers: `.js-open-add-partial` with `data-clin-id`, `.js-open-add-finance-line` with `data-clin-id` and optional `data-shipment-id`. `log_payment_modal.html` is **not** included on Finance Audit. Payment Activity panel is read-only; edit on shipment Paid/Customer Pay cells. `refreshClinRow` always renders CLIN Paid/Customer Pay as non-clickable rollups.
- **`add_finance_line_modal.js`** depends on `window.financeClinList` and `window.financeShipmentsByClin` on Finance Audit. Opened via `.js-open-add-finance-line` (not a header button). Chains `add_finance_line` or `add_partial_finance_line`, then `log_finance_line_payment` when Amount Paid > 0. Amount Paid mirrors Amount Billed by default (`data-manually-edited`). The `add_finance_line` endpoint must return `finance_line_id` in its success response.
- **`_sync_clin_ship_fields`:** Always call `_sync_clin_ship_fields` after creating a `ClinShipment` (including from `add_partial_shipment` and `create_shipment`) so CLIN `ship_qty`, `ship_date`, and `pod_date` stay accurate as rollups of child shipments (`pod_date` = MAX of non-null shipment `pod_date` values, or `None` when none). Also call it after `ClinShipment.pod_date` is saved via the Transactions edit modal (`transaction_edit_field`). After _sync_clin_ship_fields is called, add_partial_shipment also backfills clin.unit_price and clin.price_per_unit from item_value / order_qty and quote_value / order_qty respectively, if those fields are NULL and the division is safe. This is a one-time self-healing write for migrated contracts that have value totals but no per-unit prices. The guard if clin.unit_price is None ensures the backfill never overwrites a user-entered value.
- **`_recompute_clin_payment_rollup`:** Call after any shipment paid/customer-pay change (`payment_history_api` clinshipment POST/DELETE for `partial_paid_amount` / `partial_wawf_payment`, and `add_partial_shipment` when initial paid/wawf are set). Sets CLIN `paid_amount` / `wawf_payment` from `SUM(shipment columns)` via `save(update_fields=...)`. Only applies to converted CLINs (callers run after shipment money changes; CLINs with no shipments are not touched by this helper).
- **`ClinShipments.addNewShipment()`** is retired as a user entry point. Do not call it or wire new UI to it; the **Add New Shipment** button uses `js-open-add-partial` and the shared modal instead. The function may remain in `clin_shipments.js` for legacy references only.
- NSN and Supplier modals for the CLIN form are in `contracts/templates/contracts/modals/supplier_modal.html` and `nsn_modal.html`. The modal JS (`openSupplierModal`, `openNsnModal`, search/pagination helpers, and clear handlers) is defined in `clin_form.html`'s `extra_scripts` block. Element IDs `id_nsn`, `nsn_display`, `id_supplier`, and `supplier_display` are referenced by both the modal result wiring and the form — do not rename them without updating the script and modal templates together.
- **`clin_copy_defaults` endpoint (GET `/contracts/api/clin/<id>/copy-defaults/`):** Returns safe-to-copy defaults from an existing CLIN. Company-scoped. Never returns `item_number`, `item_type`, `order_qty`, `item_value`, `quote_value`, or any payment fields. The four supplier/NSN targets (`#id_supplier`, `#supplier_display`, `#id_nsn`, `#nsn_display`) are set directly by JS — the modal pickers (`openSupplierModal`, `openNsnModal`) are NOT invoked during a copy-from apply. `clin_po_num` is also returned and set on `#id_clin_po_num`. Both `po_number` and `clin_po_num` are copied. Match button state is managed by `updateMatchButtonState('nsn'|'supplier')` — call it after any change to `#id_nsn` or `#id_supplier` hidden inputs, including modal select, copy-from apply, and clear. Do not add Bootstrap Icons to `clin_form.html` — use inline SVG only.
- JS files in `contracts/static/contracts/js/` are tightly bound to specific template IDs and form names; changing template element IDs or form field names breaks the JS
- **CSS architecture — no Tailwind:** This project does not use Tailwind in any form. Styling is Bootstrap 5 plus the project's own three-file CSS system. When editing templates:
  - New component or button styles → `static/css/app-core.css`
  - New utility/helper classes → `static/css/utilities.css`
  - New color tokens or dark mode overrides → `static/css/theme-vars.css`
  - **Do not add wildcard `button:not(...)` CSS rules** in `app-core.css` or elsewhere. All buttons must be explicitly styled. Bare `<button>` elements without classes are a bug to be fixed, not caught by a wildcard.
  - If you encounter Tailwind utility classes in a template you are already editing, replace them with Bootstrap 5 equivalents or named classes from `app-core.css`. Do not leave Tailwind classes in place.
  - Inline `style` attributes are acceptable for one-off layout fixes but prefer a named class in `app-core.css` for anything reusable or that requires a hover/focus/pseudo-element state.

### Before changing exports/reports
- `contracts/utils/excel_utils.py` — wraps openpyxl with a lazy-import pattern to avoid NumPy conflicts; do not add direct `import openpyxl` elsewhere in the app
- `contracts/views/contract_log_views.py` — export logic reads CLIN fields by name; field renames here must be propagated
- `contracts/views/folder_tracking_views.py` — Excel export maps `FolderTracking` field names directly to column headers

### Before changing permissions/security logic
- `contracts/views/mixins.py` — `ActiveCompanyQuerysetMixin` raises `PermissionDenied` without active company
- `contracts/views/code_table_views.py`, `company_views.py`, `admin_tools.py` — all gated behind `user.is_superuser` checks; do not weaken to `is_staff`
- `contracts/context_processors.py` — reminder data is already scoped by `request.active_company`; adding unscoped queries here would leak data

---

## 4. Local Architecture / Change Patterns

**Multi-tenancy is pervasive.** Every model with user-visible data has a `company` FK. Querysets must be filtered by `request.active_company`. Use `ActiveCompanyQuerysetMixin` on CBVs; manually filter in function-based views.

**Views are fat orchestrators.** Business logic lives in views, not in dedicated service layers. `ContractManagementView` contains substantial orchestration logic. There is no single `services.py`; **`contracts/services/`** holds focused service modules (SharePoint helpers, **DFAS import** — see `CONTEXT.md`). New domain workflows that are not request-bound may add modules there; keep views/templates out of service packages.

**DFAS payment import (Phase 1 + 2, 2026-05; updated 2026-06):** Pipeline is `dfas_parser.py` (parse) → `dfas_matcher.py` (match) → `dfas_import.py` (persist + `finalize_import_batch`, shipment auto-assign, `rematch_import_batch`). Matcher now uses direct Call-No-first Contract lookup instead of IDIQ-first gating. Do not reintroduce IDIQ-first gating in the matcher. `matched_idiq` is populated purely as informational from the matched contract. New `shipment_missing` status is set when the parent CLIN has multiple shipments and a unique `item_value` match cannot be resolved automatically (via `auto_assign_shipment()`). Finalization branches based on `matched_shipment_id`: if present, payment applies to the shipment and rolls up to the CLIN; if null, it pays directly on the CLIN (legacy path). Re-matching is orchestrated by `rematch_import_batch()` and triggered via `/contracts/dfas-imports/<batch_id>/rematch/`. `PaymentHistory.payment_amount` has **no** minimum validator. `DfasImportBatch` / `DfasImportRow` are audit tables. **UX:** `dfas_import_views.py`, templates under `contracts/dfas_import_*.html` + `dfas_contract_matcher_modal.html`, JS `dfas_import_review.js`. **New modals:** use Bootstrap 5 `modal` / `modal-dialog` components. **Contract lookup:** prefer JSON `contracts:contract_search`. **Per-row DFAS resolutions:** add new `action` branches (e.g. `assign_shipment`) in `dfas_import_resolve_row_view` only; avoid separate URL patterns per action.
  - `resolve_unified` is the preferred resolve action going forward for contract/CLIN/shipment assignment. The older `assign_clin`, `assign_shipment`, and `find_contract` actions remain for compatibility but the UI no longer calls them directly.

**Matching / lookup patterns (external contract numbers):** When matching externally sourced contract numbers against the STATZ database, normalize both sides using `normalize_contract_number()` from `contracts/services/dfas_matcher.py` and `_norm_qs()` for the ORM-annotated queryset side. Do not use raw string equality on `contract_number` fields when the source is outside STATZ (for example DFAS CSVs, other imports, or external API feeds).

**Forms own validation, but views own object creation.** `ClinForm` intentionally strips NSN/Supplier errors because the view handles those objects separately. Do not move that responsibility without updating both sides.

**AJAX/HTMX patterns are common.** Many views return HTML fragments (notes list, shipments, splits, payment history popup) for HTMX targets. These views often have both a "full page" and "partial" rendering path. Be careful not to break partial rendering when editing view context.

**Generic relations are used for Notes and PaymentHistory.** Both use `ContentType` + `object_id`. Do not add new relationships to `Note` or `PaymentHistory` by adding direct FKs — the generic relation is intentional. When querying, always pass `content_type` + `object_id` explicitly.

**`signals.py` is intentionally empty.** Signal handling for contracts was moved to `transactions/` and `users/`. Do not add new signals to `contracts/signals.py` without understanding the audit trail in `transactions/`.

**No background tasks.** There is no Celery integration. `ExportTiming` records timing data during request-time exports; it is not a background job.

**Cancel Contract is a page, not a modal.** `ContractCancelView` at `/<pk>/cancel/` is a `DetailView`-style page (like Close). Do not revert it to a modal or AJAX pattern. The file `contracts/templates/contracts/includes/cancel_contract_modal.html` is dead — do not include it in any template.

---

## 5. Files That Commonly Need to Change Together

### Adding a field to `Contract`
- `contracts/models.py` + new migration
- `processing/models.py` `QueueContract` / `ProcessContract` and finalization mapping if the field is part of import or staging edit
- `contracts/forms.py` (`ContractCloseForm`/`ContractCancelForm` only if close/cancel flows need it)
- `contracts/views/contract_views.py` (management/detail context; Transactions modal wiring in templates/JS when the field is user-editable)
- `contracts/templates/contracts/contract_management.html`, `contract_detail.html`
- `contracts/views/contract_log_views.py` (if it should appear in exports)
- `contracts/CONTRACTS_APP_CURRENT_STATE.md` (living doc)

### Adding a field to `Clin`
- `contracts/models.py` + new migration
- `contracts/forms.py` (`ClinForm`, especially `clean()`)
- `contracts/views/clin_views.py`, `api_views.py` (update-field API)
- `contracts/templates/contracts/clin_form.html` (create flow only) and `clin_detail.html` (read-only display with Transaction edit buttons on labels for tracked fields)
- `contracts/views/contract_log_views.py` (if exported)
- `processing/models.py` `QueueClin` (if imported)
- `transactions` app tracked-fields list (if auditable)

### Adding a new workflow action (e.g., contract toggle/status change)
- `contracts/views/contract_views.py` (handler function)
- `contracts/urls.py` (new URL pattern)
- `contracts/templates/contracts/contract_management.html` (UI trigger)

### Adding or renaming a code table (e.g., new `ContractType`)
- `contracts/models.py` (new model or field)
- `contracts/forms.py` (form widget update)
- `contracts/views/code_table_views.py` (register in admin page)
- `contracts/templates/contracts/code_table_admin.html`

### Changing folder tracking stacks
- `contracts/models.py` (`FolderTracking.stack` choices and `STACK_COLORS`)
- `contracts/views/folder_tracking_views.py` (color helpers, stack logic)
- `contracts/templates/contracts/folder_tracking.html` (color rendering)
- `contracts/utils/excel_utils.py` or folder tracking export helpers (column mapping)

### Changing supplier display in contracts
- `contracts/views/supplier_views.py`
- `suppliers/models.py` (source model — read-only from contracts)
- `contracts/templates/contracts/supplier_detail.html`, `supplier_list.html`
- `contracts/static/contracts/js/supplier_modal.js`
- **Supplier flag display rule:** When rendering a supplier name anywhere in the contracts app, check `supplier.probation` and `supplier.conditional`. Apply `.supplier-flag-probation` if probation is true (takes priority). Apply `.supplier-flag-conditional` if conditional is true and probation is false. Plain text if neither. Do not add inline styles — use these CSS classes only.

### Dynamic Contract Tracker — API inventory (`contracts/views/dynamic_tracker_views.py`, `contracts/urls.py`)
Authenticated, company-scoped (match `TrackerSchema.company` to `request.active_company` when set). Main UI: `contracts/templates/contracts/dynamic_tracker.html`.

| Method | Path | URL name | Purpose |
|--------|------|----------|---------|
| GET | `/contracts/dynamic-tracker/` | `tracker_list` | List trackers |
| POST | `/contracts/dynamic-tracker/create/` | `tracker_create` | Create tracker |
| GET | `/contracts/dynamic-tracker/<schema_id>/` | `tracker_detail` | Grid page |
| GET | `/contracts/api/dynamic-tracker/<schema_id>/schema/` | `tracker_api_schema` | JSON columns |
| POST | `/contracts/api/dynamic-tracker/<schema_id>/add-column/` | `tracker_add_column` | Add column |
| POST | `/contracts/api/dynamic-tracker/<schema_id>/column/<column_id>/update/` | `tracker_update_column` | Edit column |
| POST | `/contracts/api/dynamic-tracker/<schema_id>/column/<column_id>/delete/` | `tracker_delete_column` | Delete column |
| POST | `/contracts/api/dynamic-tracker/<schema_id>/reorder-columns/` | `tracker_reorder_columns` | Reorder |
| POST | `/contracts/api/dynamic-tracker/<schema_id>/column-width/` | `api_update_column_width` | Persist `width_px` on user column or width in `system_col_widths` for `__contract__` / `__po__` / `__close__` |
| POST | `/contracts/api/dynamic-tracker/<schema_id>/add-record/` | `tracker_add_record` | Add row |
| POST | `/contracts/api/dynamic-tracker/record/<record_id>/update/` | `tracker_update_record` | Cell / highlight |
| POST | `/contracts/api/dynamic-tracker/record/<record_id>/delete/` | `tracker_delete_record` | Delete row |
| POST | `/contracts/api/dynamic-tracker/record/<record_id>/close/` | `tracker_close_record` | Soft-close row |
| GET | `/contracts/api/dynamic-tracker/search-contracts/` | `tracker_search_contracts` | Contract/PO typeahead (`q`) |

### Reminders popup window
- `contracts/views/reminder_views.py` — `reminders_popup`, `reminders_popup_add`, `reminders_popup_edit` views
- `contracts/templates/contracts/reminders_popup_base.html` — bare base template (no nav chrome)
- `contracts/templates/contracts/reminders_popup.html` — popup content template
- `contracts/urls.py` — `reminders_popup`, `reminders_popup_add`, `reminders_popup_edit` URL patterns
- `contracts/templates/contracts/contract_base.html` — `openRemindersPopup()` JS function; sticky-footer **Reminders** pill (`id="contracts-reminders-footer-pill"`) opens the popup directly
- `reminders_popup_add` and non-AJAX `reminders_popup_edit` redirect to `contracts:reminders_popup` with no query string (default **Due Now** view). Other popup flows use `HTTP_REFERER` where applicable (`toggle_reminder`, `delete_reminder` non-AJAX).
This pattern (popup_base + popup view + popup_add + popup_edit) is the approved pattern for future popup windows (e.g. Notes).

**Reminders popup v1 (2026-05):** Default view is `due_and_overdue` (no query params): non-completed reminders with `reminder_date <= today`, matching the footer pill (`footer_overdue_count` + `footer_due_today_count`). Toggle **Due Now** vs **All Pending** (`?due=all&status=pending`, all non-completed sorted by due date ASC, paginated 50). **Completed** is a separate link (`?status=completed`). Card body opens `#reminderDetailModal` (read-only; **Mark Complete** via `fetch` to `mark_reminder_complete` — no `<form>` in that modal). Pencil opens `#editReminderModal`; save uses AJAX to `reminders_popup_edit` and updates the card in the DOM. Delete is a text link + `confirm()` + AJAX to `delete_reminder`. After complete/delete (and on popup load), `window.opener.patchReminderFooterPill()` syncs the parent pill when an opener exists.

**ReminderListView (`/contracts/reminders/`):** On a fresh visit with no query params it still defaults `status` to `pending` (all non-completed) with the existing `?due=` chip behavior (`due=all` sentinel = no due slice). Popup and list defaults differ intentionally.

### Reminders sidebar removed (2026-05)
- **Reminders sidebar removed (2026-05).** The slide-out reminder sidebar panel in `contract_base.html` has been removed. The footer Reminders pill now calls `openRemindersPopup()` directly, opening the standalone reminders popup window (`/contracts/reminders/popup/`). All sidebar HTML, JS, and CSS (`.reminder-card*`, `.reminders-panel-*`) have been deleted. `contracts/static/css/components.css` is now an empty deprecated stub; all styles live in `contracts/static/contracts/css/components.css` which is loaded by `contract_base.html`. After any action in the popout reloads the popout page, `window.opener.patchReminderFooterPill()` is called to sync the parent page's footer pill count.
- `contracts/context_processors.py` — `reminders_processor` still exposes `reminders`, `overdue_count`, `due_count`, `pending_count`, `total_reminders_count`, and related keys for other consumers (e.g. `/contracts/reminders/` list chips). **Footer pill and popup header pills** use the same definitions: `footer_overdue_count` (non-completed, `reminder_date < today`) and `footer_due_today_count` (non-completed, `reminder_date` exactly today). Footer badge sum = `footer_overdue_count + footer_due_today_count`; pill color red if `footer_overdue_count > 0`, else green. Do not repurpose `due_count` / `overdue_count` / `total_reminders_count` for the footer pill.
- `contracts/templates/contracts/contract_base.html` — sticky-footer **Reminders** pill uses `footer_overdue_count` / `footer_due_today_count` for badge visibility, count, and red/green styling as above (`id="contracts-reminders-footer-pill"` for `patchReminderFooterPill` lookups).
- **Live AJAX footer count (2026-05):** `window.patchReminderFooterPill()` in `contract_base.html` GETs `contracts:reminder_counts_api` and updates the pill badge and red/green button classes without reload. Call it after AJAX reminder actions from `#noteFullViewModal` / notes partials (`notes_list.html` / `notes_popup_tab_panel.html`), and from `reminders_popup.html` on each load when opened via `window.open` so the parent pill stays in sync after form POSTs in the popout. `toggle_reminder_completion` and `mark_reminder_complete` return JSON for `X-Requested-With: XMLHttpRequest`. Completed reminder pills on note cards use `.reminder-pill-completed` in `contracts/static/contracts/css/components.css`.
- `contracts/views/reminder_views.py` — popup flows use `toggle_reminder`, `delete_reminder`, `reminders_popup_add`, `reminders_popup_edit`, and referer redirects; standalone edit/complete URLs remain for non-popup callers.

### CLIN detail page layout (2026-04-24)
- `contracts/templates/contracts/clin_detail.html` — section markup. New sections must follow the `<section id="clin-*"> > .card.clin-section-card.clin-card-* > .card-header.clin-section-header + .card-body` pattern, and ship with a matching `<a class="nav-link" href="#clin-*">` entry inside `#clin-page-nav`.
- `contracts/static/contracts/css/components.css` (under `/* === CLIN Detail Page === */`) — sidebar, content, card, header, label, and value styles. Colour tokens use `var(--bs-*)`; new `.clin-card-*` accent rules belong here next to the existing ones. The sidebar is `position: fixed` at `left: 0`, `top: 4rem`; if the top navbar height changes, update `top` and `height: calc(100vh - 4rem - 3.5rem)`. The 200px width is set in two places (`.clin-detail-sidebar { width }` and `.clin-detail-content { margin-left }`) — both must match if changed. The full-width override targets `.clin-detail-page main > div.mx-auto` with `!important` so it can beat the inline `style="width: 75%"` on `contract_base.html`'s container; do not weaken that selector or the layout reverts to 75 %.
- `contracts/templates/contracts/contract_base.html` — provides the `{% block body_class %}{% endblock %}` hook on the outer wrapper. Other contracts pages can opt into similar layout overrides by setting `body_class` to their own page-level class.
- `contracts/templates/contracts/contract_management.html` — the Shipments modal links to `/contracts/clin/<id>/#shipping-information`, so the Shipping section in `clin_detail.html` keeps `id="shipping-information"` instead of `id="clin-shipping"`. Do not rename without updating that link.
- The Financials section is always visible. Do not reintroduce `#financial-details-toggle` / `#financial-details-section` collapse logic. The Tailwind responsive grid (`md:grid-cols-12` / `md:col-span-4`) is replaced with Bootstrap `row g-3` / `col-md-4`.
- Bootstrap ScrollSpy is initialised in JS (`new bootstrap.ScrollSpy(document.body, { target: '#clin-page-nav', smoothScroll: true })`), not via `data-bs-spy` attributes. A `MutationObserver` on `#clin-transaction-history` calls `scrollSpy.refresh()` after the AJAX history fetch so newly inserted content is tracked.

### SharePoint path resolution
- `IdiqContract.get_sharepoint_documents_url()` follows the same SharePoint URL construction pattern as `Contract.get_sharepoint_documents_url()`, but uses `self.closed` (boolean) instead of `status.description`, and always resolves company via `Company.get_default_company()` because `IdiqContract` has no company FK.
- `Contract.get_sharepoint_relative_path()` — single source of truth for contract SharePoint folder paths (regular, closed/cancelled, IDIQ delivery orders, company prefix). Do not duplicate path construction in views or `sharepoint_paths.py` for `Contract` rows.
- `contracts/services/sharepoint_paths.py` — strict validation (`is_modern_sharepoint_path`), structured resolution (`resolve_contract_folder_path` returns `{path, source, legacy_detected}`). IDIQ-only rows use `build_idiq_pattern_path` / `resolve_idiq_folder_path` (no `Company` FK). Use `join_path()` for IDIQ pattern segments only.
- `contracts/services/sharepoint_service.py` — Graph wrappers (`list_folder_contents`, `fallback_to_root`, `normalize_legacy_path`). `list_folder_contents` raises `SharePointNotFound` on 404; the views catch it and walk up parents, ultimately falling through to `get_root_fallback_path(contract)`. **`delete_file_by_id`** is internal/temp-file cleanup only (logs a warning on non-204) — do **not** use it for user-facing deletes; use **`delete_item_by_id`** instead (raises `SharePointError` on failure).
- `contracts/views/documents_views.py` — `contract_details_api` and `_list_sharepoint_files` both surface `legacy_detected`; `_list_sharepoint_files` also surfaces `fell_back_to_root` when the resolved path 404s. Contract queries use `select_related('idiq_contract', 'status', 'company')`. `create_folder_api` (POST `api/create-folder/`) authorizes via `_contract_for_request` then calls `sharepoint_service.create_folder`. User-facing document browser APIs: `download_file_api` (POST, streams bytes), `delete_file_api` (POST, staff-only, uses `delete_item_by_id`), `folder_weburl_api` (GET).
- `contracts/templates/contracts/documents_browser.html` — `legacyPathDetected` JS flag persists across the two-API-call init flow; both warning banners (`legacy_detected`, `fell_back_to_root`) are appended to `#alert-banner`. Saving the path via `setCurrentPath()` clears the legacy flag. Multi-select checkboxes, **Actions** dropdown menu (Save Path, Open in SharePoint, Download, staff-gated Delete), and Bootstrap confirmation modal for deletes. Requires Bootstrap 5 JS bundle for dropdown/modal. Breadcrumb DOM position must not change.
- `SHAREPOINT_PATH_PREFIX` setting defines the global canonical root when `Company.sharepoint_documents_path` is unset. `get_contract_documents_root()` in `sharepoint_service.py` remains the documents-root helper for browser config and legacy path normalization.
- When the path naming convention changes, update `Contract.get_sharepoint_relative_path()` (and IDIQ helpers in `sharepoint_paths.py` if IDIQ parent folders change). Validation is prefix-based and stays the same.
- Contract field for stored folder path is `files_url` (NOT `file_url`). Status values that trigger the Closed Contracts segment: `Closed`, `Canceled` (canonical `ContractStatus.description` spelling, one L).
- `intake_draft_documents_browser_view`, `intake_draft_details_api`, and `set_draft_file_path_api` are intake-facing views that live in `documents_views.py` because they reuse the shared browser template and SharePoint service layer. They import from `intake.*` internally (lazy imports inside the function body) to avoid circular imports at module level.
- All file API endpoints now support dual-gate authorization: `contract_id` for canonical contracts, `draft_id` for intake drafts. Add this same dual-gate to any new file API endpoints added in the future.

### Notes popup window
- `contracts/views/note_views.py` — `notes_popup`, `notes_popup_tab`, `note_detail_json` views
- `contracts/templates/contracts/notes_popup_base.html` — bare base template (no nav chrome)
- `contracts/templates/contracts/notes_popup.html` — popup content template
- `contracts/templates/contracts/partials/notes_popup_tab_panel.html` — tab panel partial
- `contracts/urls.py` — `notes_popup`, `notes_popup_tab_finance`, `notes_popup_tab_contract`, `notes_popup_tab_clin`, `note_detail_json` URL patterns
- `contracts/templates/contracts/contract_management.html` — `openNotesPopup()` JS function, follow-me hook, pop-out button in notes header

All popup CRUD actions refresh the current tab in-place; no cross-window data sync. The popup exposes `window.isPinned` (boolean) read by the main window before pushing a new contract URL to an unpinned popup.

**Notes popup tab panel UI:** `partials/notes_popup_tab_panel.html` uses compact cards (3-line clamped body, type pill, meta row with `border-top`, edit/delete on the meta row). The clickable body (`.js-note-expand`) and meta-row reminder pill open **`#noteFullViewModal`** (Bootstrap `modal-lg`, scrollable) for full text / reminder details and optional Mark Complete toggle (`contracts:toggle_reminder`). Styles: `contracts/static/contracts/css/components.css` under `/* === Note Card Redesign */`. Inline `<script>` in the partial registers delegated listeners once via `window.__contractsNoteFullViewBound` and dedupes duplicate `#noteFullViewModal` ids; **`notes_popup.html`** must call `activateScriptsInNotesTabPanel(panel)` after each `innerHTML` refresh so that script runs (scripts in `innerHTML` are not executed by default).

**Contract management `notes_list.html`:** Matches the same Bootstrap card / `#noteFullViewModal` behavior as the popup tab panel (no Tailwind). **`ContractManagementView`** sets `current_user_has_reminder` / `current_user_reminder` on notes in all relevant loops; **`get_clin_notes`** and **`delete_note`** AJAX refresh annotate via **`annotate_notes_for_current_user`**. The partial’s script uses **`window.__contractsMgmtNoteFullViewListeners`** (once per page) plus synchronous modal dedupe and **`document.body`** append for stacking. **`contract_management.html`** exposes **`window.dedupeNoteFullViewModals()`** for fetch/note-save **`innerHTML`** refreshes; **`note_modal.js`** calls it after injecting `notes_html`. **`.js-note-expand`** must expose only **`data-note-*`** (not **`data-reminder-*`**); reminder **`data-*`** belongs on **`.js-reminder-pill`** only — body click opens note text (script passes **`hasReminder: false`** from the body path). **Edit** is shown to the note **creator** or **`Note.assigned_to`** and uses **`onclick="if(typeof openEditNoteModal==='function'){openEditNoteModal(this);} return false;"`** plus **`js-edit-note-btn`**. **`get_clin_notes`** → **`render_to_string(..., request=request)`** for this partial (CSRF in modal). **Delete** stays `<a>` + **`confirm()`**.

**Finance notes:** When creating or filtering `Note` records in the context of the Finance tab, always use `note_tag='finance'`. Never display finance-tagged notes on the contract management page or in the contract notes tab (contract-level queryset excludes them; the contract tab in the popup excludes `note_tag='finance'`).
The Add Note flow uses the same modal as Edit Note and is opened from the notes tab toolbar button instead of an always-visible inline form.

---

## 6. Cross-App Dependency Warnings

### This app depends on:
| App | What it uses |
|-----|-------------|
| `suppliers` | `Supplier`, `Contact`, `SupplierType`, `Certification`, `Classification`, `SupplierDocument` models |
| `products` | `Nsn` model (FK on `Clin`; `PROTECT` delete behavior) |
| `processing` | `SequenceNumber` for PO/TAB number defaults |
| `users` | `User`, `UserCompanyMembership`, `UserSettings`, `conditional_login_required` decorator, `request.active_company` middleware |

NSN search is dash-agnostic. `get_select_options` in `contracts/views/api_views.py` normalizes the search term using `normalize_nsn` from `processing.services.contract_utils`. Do not replace this with raw `icontains` on `nsn_code` alone — that will break dashless search again.

**`POSnippet`** — company-scoped snippet store. No `ContentType`, no audit trail, no FK to `Contract` or `Clin`. Safe to query/filter freely. `snippet_views.py` is the only view file; do not add snippet logic elsewhere.

### Apps that depend on this app:
| App | How it depends |
|-----|---------------|
| `processing` | `QueueContract`/`QueueClin` map fields to `Contract`/`Clin`; matching engine creates live `Contract`/`Clin` rows |
| `transactions` | Registers pre/post_save signals on `Contract` and `Clin`; reads a list of tracked field names — **renaming any tracked field on these models silently drops audit history** |
| `sales` | Tier-1 supplier NSN scoring reads `contracts_*` via SQL Server view `dibbs_supplier_nsn_scored` (not Django `Clin` in `matching.py`) |
| `suppliers` | Some supplier URL patterns may reverse into contracts URLs |

### Specific high-risk field names (tracked by `transactions` signals):
Fields on `Contract` and `Clin` that appear to be tracked include: `contract_number`, `po_number`, `due_date`, `award_date`, `status`, and other core financial/date fields. Before renaming any of these, search `transactions/` for the field name to confirm it is not in a TRACKED_FIELDS list or hard-coded signal handler.

### Template / partial sharing:
- `notes_list.html` and `note_modal.html` are included in contract management, CLIN detail, and supplier detail templates. Changes to their expected context keys break all three locations.
- `payment_history_popup.html` is included from multiple views; its context variables (`payment_history`, `entity_type`, `entity_id`) must stay stable.
- `notes_popup_tab_panel.html` is popup-only (AJAX-loaded into the notes popup). **`notes_list.html`** on **contract management** now mirrors the same Bootstrap card UX and the same **current-user** reminder fields (`current_user_has_reminder` / `current_user_reminder`) as the popup: annotate in **`ContractManagementView`**, **`annotate_notes_for_current_user`** / **`bulk_annotate_notes_for_current_user`** in **`note_views`**, and **`annotate_notes_for_current_user`** in **`get_clin_notes`**. Preserve **`js-edit-note-btn`**, **`data-note-action="edit"`**, **`onclick`** guard + **`openEditNoteModal`**, and the **note-only** **`data-*`** split on **`.js-note-expand`** vs **`.js-reminder-pill`**. Any **`render_to_string('contracts/partials/notes_list.html', ...)`** must pass **`request=request`** (modal contains **`{% csrf_token %}`**).

---

## 7. Security / Permissions Rules

- **Never remove `ActiveCompanyQuerysetMixin`** from a view that returns company-scoped data. Without it, users will see records from other companies.
- **`request.active_company` is set by middleware** (`users` app). Do not query `Company`-scoped models without it.
- Superuser-only views use `@user_passes_test(lambda u: u.is_superuser)`. Do not downgrade to `is_staff` — these views expose company config, logo upload, and bulk SharePoint updates.
- Note **delete** still requires `request.user == note.created_by or request.user.is_staff` in views (`delete_note`). **Edit** in `note_update` and **`note_detail_json`** `can_edit` / `can_manage_reminder`: `note.created_by == request.user OR note.assigned_to == request.user` only — **no `is_staff` exception** (staff is most users; `Note.assigned_to` is the delegation mechanism). **UI:** In **`partials/notes_popup_tab_panel.html`** and **`partials/notes_list.html`**, the **Edit** button is shown when `request.user == note.created_by or request.user == note.assigned_to`. The meta row reads **Assigned to** *username* **on** *date*: `assigned_to.username` if set, else `created_by.username`. Reminder create/update/delete on a note in `note_update` / `add_note` follows the same edit permission; `reminder_user` is chosen from POST (any active user, default `request.user`). The meta-row **reminder pill** (when `current_user_has_reminder`) and the full note body open **`#noteFullViewModal`**; Mark Complete / Incomplete POSTs to `contracts:toggle_reminder`.
- Reminder completion toggle requires ownership check. Same pattern.
- Exports (contract log, folder tracking) are accessible to any logged-in user in the active company — treat them as sensitive; do not make them publicly accessible.
- Audit fields (`created_by`, `modified_by`) must be populated by views on create/update. Do not skip them — the contract log and admin both surface these.
- Some shipment API endpoints are CSRF-exempt (by design for HTMX). Do not mark additional endpoints CSRF-exempt without careful review.

---

## 8. Model and Schema Change Rules

- **ContractPackaging financial fields:** `quote_amount` and `amount_paid` are updated via `PaymentHistory` rows (entity_type `contract_packaging`, payment types `packaging_quote` / `packaging_paid`). The write-back from `new_total` after a payment delete must also update the stored field. `invoice_number` and `payment_date` are updated via `update_packaging_finance`. `packhouse` and `notes` are updated via `update_packaging_details`. Do not add direct form-POST edit paths for the financial fields — they must go through PaymentHistory to preserve the audit ledger. Note that `ContentType.objects.get_for_model(ContractPackaging).model` returns `'contractpackaging'` (no underscore); the URL/JS-facing `entity_type` is `'contract_packaging'` (with underscore). Keep both forms in sync in `payment_history_views.py`.
- **Before renaming any `Contract` or `Clin` field:** search `transactions/` (signals, TRACKED_FIELDS), `processing/` (QueueContract/QueueClin field mapping), `sales/` (matching.py, views), and all `contracts/views/*.py` for string references to the field name.
- **`Nsn` FK on `Clin` uses `PROTECT`.** You cannot delete an `Nsn` that has CLINs. Any migration that changes this behavior will affect `products` app.
- **`Company` FK on most models uses `PROTECT`.** Deleting a `Company` will fail if any Contract, Clin, Note, Reminder, or GovAction exists for it. This is intentional.
- **Generic relations on `Note` and `PaymentHistory`** (`content_type` + `object_id`) are stable. Do not add direct FKs. If adding a new attachable model, follow the existing `ContentType` pattern.
- **Compound indexes exist** on `Contract` and `Clin` (e.g., `(status, due_date)`, `(contract, due_date)`). Check `models.py` Meta before adding overlapping indexes.
- **`ClinShipment` financial fields** (`quote_value`, `item_value`, `paid_amount`, `wawf_payment`) are nullable and optional. They exist for contracts that use partial shipment financial tracking (~25% of contracts). Never assume these fields are populated — use `|default:0` in templates or `or Decimal('0.00')` in Python when using them in calculations. **Derived quote/item (Slice 2A):** `auto_quote_value` and `auto_item_value` are the single source of truth for derivation (`ship_qty ×` CLIN per-unit prices). New shipments store derived values from the Add Shipment modal; users cannot hand-edit quote/item there. Legacy rows may still have stored values that differ from current QTY × per-unit price until qty is changed or a future recompute job runs. **Finance lines on partials:** `ContractFinanceLine.partial` points at a `ClinShipment` when the line is shipment-scoped (`ClinShipment.finance_lines` reverse accessor). CLIN-level lines keep `partial` NULL. Do not mix these up in querysets — `Clin.adjusted_gross` only includes finance lines with `partial__isnull=True`.
- **`AuditModel` base class** is used by ~8 models. Changes to `AuditModel` fields affect all of them simultaneously; write one migration for the base or confirm Django handles it correctly.
- **`ExportTiming`** stores JSON in `filters_applied`. If the filter shape changes in the log view, old `ExportTiming` rows may cause `json.loads` errors — handle gracefully.

---

## 9. View / URL / Template Change Rules

- **URL namespace is `contracts`.** There are ~90 named patterns. Before renaming any URL name, search the entire codebase for `contracts:<url_name>` (in templates with `{% url %}`) and `reverse('contracts:...')` in Python.
- **`ContractManagementView`** builds a large context dict from multiple queries (CLINs, notes, splits, GovActions, expedite, folder tracking). Adding a new context key is safe; removing or renaming an existing key requires checking `contract_management.html` and all its `{% include %}` partials.
- **`openShipmentsModal(clinId)`** on `contract_management.html` opens the read-only shipments modal and loads HTML from `GET /contracts/api/shipments/<clin_id>/?mode=detail`. If the CLIN card markup or the JavaScript that rebuilds the card (e.g. `fetchClinDetails`) is refactored, keep the **Shipments** button and its `onclick="openShipmentsModal(...)"` in sync with the server-rendered CLIN card (including `id="cd-shipments-btn"` on the initial SSR button when applicable).
- **HTMX partial views** (notes, shipments, splits, payment history) return HTML fragments. These views have an implicit contract with the frontend: the element IDs and `hx-target` selectors in templates must match. Changing response structure without updating `hx-target` references breaks the UI silently.
- **`contract_base.html`** (inferred from `contracts/templates/contracts/`) may serve as a base template for other templates in this app. Changing its block structure requires updating all child templates.
- **`clin_shipments.js`, `contract_splits.js`, `note_modal.js`, `supplier_modal.js`** reference DOM element IDs and form field `name` attributes. If you rename form fields or template element IDs, update these JS files.
- **`note_modal.js`:** The save handler is bound once on `DOMContentLoaded`. If duplicate POSTs to `note/add/` or `note/update/` reappear, check `base_template.html` and especially `contract_base.html` for duplicated `{% block %}` names in the inheritance chain (nested `{% block extra_js %}`) before assuming a bug in the JavaScript.
- **Note views and Django messages:** Do not call `messages.success()` before the AJAX branch check in note views. AJAX callers never consume Django messages (no redirect), so they persist as sticky banners on the next full page load. Pattern: check the `X-Requested-With: XMLHttpRequest` header first, return `JsonResponse` for AJAX; only call `messages.success()` in the non-AJAX `else` branch before `HttpResponseRedirect` / `redirect`.
- **Note modal reminders:** `reminder_text` is set in JavaScript to the **final** note body after client-side timestamp / “Add to Note” merge (`note_modal.js` and the notes popup inline save). The main modal uses `id_note_addition` + `id_note` in edit mode; add mode hides the addition box. Timestamp format: `--- MM/DD/YYYY HH:MM AM/PM ---`. The notes popup edit modal (`notes_popup_edit_modal.html`) mirrors the same behavior. Do not reintroduce a separate reminder-body textarea that could diverge from saved note text without updating those POST lines.
- **Supplier detail templates** (`contracts/templates/contracts/supplier_*`) are rendered by `contracts/views/supplier_views.py` but read from `suppliers` models. Template changes here do not affect `suppliers` app templates.

---

## 10. Forms / Serializers / Input Validation Rules

- **`ClinForm.clean()`** silently removes NSN and Supplier validation errors — the view handles those objects separately via modal creation flows. Do not add hard validation on those fields inside the form.
- **`ClinForm.clean()`** auto-calculates `item_value = order_qty × unit_price` and `quote_value = order_qty × price_per_unit`. If you add new quantity/price fields, update this logic or the calculated values will be stale.
- **Contract number uniqueness** on create/update is enforced in Processing finalization and related services; if you add a similar check elsewhere, use an `exclude(pk=...)` pattern when updating an existing row.
- **`CompanyForm`** syncs `UserCompanyMembership` rows inside `save()`. If you override `save()` or call `form.save(commit=False)`, you must call `form.save_m2m()` or the membership sync will not run.
- **`BaseFormMixin`** auto-applies CSS classes via widget inspection. If a new widget type is introduced, add it to `BaseFormMixin` to keep styling consistent.
- **`ActiveUserModelChoiceField`** filters users to `is_active=True`. All user-selection dropdowns in this app must use this field, not bare `ModelChoiceField`.

### Contract status strings and `ContractCloseView`
- `ContractStatus.description` values in the database must be referenced **exactly** in code: `"Open"`, `"Closed"`, and `"Canceled"` (one L). Do **not** use `"Cancelled"` in lookups, filters, or new logic — it will not match the row in `contracts_contractstatus` (e.g. id=3 is `Canceled`).

- **`ContractCloseView`** is a `DetailView`: `GET` renders the close / confirmation / already-closed page; `POST` applies the close and redirects. It is **not** a form-based `UpdateView` — the empty `ContractCloseForm` is compatibility-only.

---

## 11. Background Tasks / Signals / Automation Rules

- **No Celery tasks in this app.** All processing is synchronous.
- **`contracts/signals.py` is empty by design.** Signal handlers related to contracts live in `transactions/signals.py` (audit trail) and `users/signals.py`.
- **`transactions` app signals fire on every `Contract.save()` and `Clin.save()`.** This means: every view that saves a Contract or Clin triggers an audit row in `transactions`. If you bypass `.save()` (e.g., use `queryset.update()`), the audit trail will be skipped silently.
- **`context_processors.reminders_processor`** fires on every request. It queries reminders filtered by `request.active_company`. If this processor is slow, it affects every page load. Do not add heavy queries here.
- **`initialize_sequence_numbers`** management command seeds PO/TAB counters from existing contracts. Must be run after bulk data imports to avoid duplicate sequence numbers.
- **`ExportTiming`** records export duration during request-time. It degrades gracefully; it does not affect correctness if it fails.
- **`Write a Release Note`** If your change is user-facing or significant, create a release note in the `release_notes/` directory following the strict frontmatter rules in Section 16.

---

## 12. Testing and Verification Expectations

**Current state:** `contracts/tests.py` is a stub. No automated tests exist for this app.

**After any model/migration change:**
- Run `python manage.py makemigrations --check` to confirm no missing migrations
- Open Django admin at `/admin/contracts/` and verify `Contract`, `Company`, and `Reminder` displays load without error
- Create a test contract in the UI and verify the management page loads

**After view changes:**
- Manually verify the contract management page (`/<pk>/`) loads for a real contract
- Verify the CLIN create form submits without errors and the CLIN detail page loads (Transactions modal for field edits)
- Open folder tracking view and verify the stack displays correctly
- If you changed an API view, test the HTMX interaction in the browser (notes add/delete, shipment add/edit, split operations)

**After form changes:**
- Submit the ClinForm (create flow) with an empty required field and confirm validation fires
- Submit the ClinForm and confirm `item_value` is auto-calculated
- If you changed `CompanyForm`, upload a logo and verify validation catches invalid types

**After export changes:**
- Download a contract log export (CSV or XLSX) and open it — verify columns match expected headers
- Download a folder tracking export and check column alignment

**After permissions changes:**
- Log in as a non-superuser and confirm `/contracts/companies/` and `/contracts/code-tables/` return 403
- Log in as a user without an active company and confirm company-scoped views return `PermissionDenied`

**Cross-app smoke test after Contract/Clin schema changes:**
- Open the `processing` admin or queue view and verify QueueContract/QueueClin display without errors
- Check `transactions` audit log for recent records to confirm signals still fire

---

## Recent completions

- **Dashboard period boundaries (2026-05-28):** `get_period_boundaries()` in `contracts/views/dashboard_views.py` now calls `timezone.localtime(now)` as its first step to prevent UTC-offset boundary bleed. `_start_end_of_day()` updated to return `date` objects for compatibility with `DateField` range filters (post migration 0054).

## Recent fixes

- **Contract search spelling bug fixed:** `contract_search` view was filtering on `'Cancelled'` (2 L) which did not match the `ContractStatus` DB record `'Canceled'` (1 L). Fixed. Dashboard and contract log filters now use `'Canceled'` for `status__description` comparisons; treat any remaining `'Cancelled'` literal against `ContractStatus.description` as a bug.

---

## 13. Known Footguns

`clin-delete-note-cleanup-rule`: When deleting a Clin, always manually delete Notes (ContentType-linked) and their child Reminders before calling `clin.delete()`. These do NOT auto-cascade. Pattern: get Clin ContentType → filter Notes → delete Reminders on those Notes → delete Notes → then delete Clin.

1. **Renaming tracked fields without updating `transactions` signals.** The `transactions` app stores field names as strings. A rename will stop capturing that field in the audit trail with no error raised.

2. **Using `queryset.update()` instead of `.save()` on Contract/Clin.** This bypasses the `transactions` signals entirely. Always use `.save()` unless you intentionally want to skip the audit trail (rare; document it if so).

3. **Removing `ActiveCompanyQuerysetMixin` from a CBV.** Will serve all companies' data to any logged-in user. This is a multi-tenancy data leak.

4. **Changing `FolderTracking.stack` choice values.** These are stored as strings in the database. Changing a value in the choices list does not migrate existing rows. Existing rows will display as unknown/invalid choices.

5. **Changing `STACK_COLORS` in `FolderTracking`.** Stack colors are referenced in the Excel export by name. A rename breaks the export color mapping.

6. **Changing the `Note`/`PaymentHistory` context variable names** in view responses. These are consumed by `notes_list.html` and `payment_history_popup.html` partials, which are included in multiple parent templates. A rename breaks all of them.

7. **Calling `CompanyForm.save(commit=False)` without calling `form.save_m2m()`.** The `UserCompanyMembership` sync runs in `save()`. Skipping it leaves membership out of sync.

8. **Adding `import openpyxl` directly.** `contracts/utils/excel_utils.py` uses lazy-loading to avoid NumPy conflicts. Import openpyxl exclusively via this utility module.

9. **Breaking the `ClinForm.clean()` auto-calculation.** `item_value` and `quote_value` are not always entered by users; they are derived. If `clean()` fails, these fields silently remain zero and financial reporting is wrong.

10. **Changing URL pattern names without searching templates.** There are ~90 named URLs. `{% url 'contracts:...' %}` is used throughout `contracts/templates/contracts/` and possibly in `sales`, `processing`, and `suppliers` templates.

11. **PO Acknowledgement Letter** — views live in `acknowledgment_views.py` only (single-e spelling). Do not recreate `acknowledgement_letter_views.py` (double-e) or legacy full-page routes.

**`AcknowledgmentLetterTemplate` (`contracts/models.py`):** DB-backed `.docx` templates for letter generation. Fields: `sharepoint_file_id`, `sharepoint_file_name`, `rev_number`, `uploaded_by`, `uploaded_at`, `is_active`. Template bytes live in SharePoint at `Statz-Public/data/V87/aFed-DOD/z-temp/templates/` (not Django media). **`activate()`** deactivates all other rows and sets `is_active=True` on this instance. **`get_active()`** returns the single active template or `None`. Staff upload on the letter page (`upload_acknowledgment_template`); each upload auto-activates. **Substitution helpers** (`acknowledgment_views.py`): `_build_letter_substitutions(letter)`, `_apply_substitutions_to_doc(doc, substitutions)`, shared pipeline `_generate_letter_pdf_bytes(letter)`, `_acknowledgment_pdf_filename(letter)` → fixed string `Purchase Order Acknowledgment Letter.pdf` (shared by send + existing-PDF lookup; one letter per contract folder). **`get_existing_acknowledgment_pdf`:** GET on page load; looks up `Purchase Order Acknowledgment Letter.pdf` in contract folder via `resolve_contract_folder_path` + `_get_drive_item`; returns base64 PDF or `exists: false`; SharePoint errors are silent (no user toast). **Preview** (`preview_acknowledgment_letter`): same PDF pipeline; **Refresh Preview** after **Save**; stale badge hidden after fresh preview. **Download PDF** / **Send to Contract Folder** enabled when preview or existing PDF loads; reset when form goes dirty. **`send_acknowledgment_to_contract_folder`:** POST; saves via `_acknowledgment_pdf_filename` + `send_pdf_bytes_to_folder` (overwrites). **`generate_acknowledgment_letter_doc` removed** — PDF only, no `.docx` export. SharePoint service: `upload_bytes_to_folder`, `convert_file_to_pdf_bytes`, `delete_file_by_id`, `download_file_bytes_by_id`, `send_pdf_bytes_to_folder`.

**`AcknowledgementLetter` due dates:** `fat_due_date` and `plt_due_date` replaced the legacy `fat_plt_due_date` field (migration `0070`). Word template placeholders: `{{FAT_DUE_DATE}}` and `{{PLT_DUE_DATE}}` (not `{{FAT_PLT_DUE_DATE}}`). Preview and send-to-folder must substitute both tokens from the saved letter row.

`acknowledgement-letter-prefill-lock`: `AcknowledgementLetter.is_user_edited` controls whether prefill runs on open. It is ONLY set to True inside `send_acknowledgment_to_contract_folder`. Do not set it in the Save view, do not set it manually in migrations, and do not add other write paths without updating the CONTEXT.md state machine docs.

**Acknowledgment letter URL names:**
| Name | View | Notes |
|------|------|-------|
| `acknowledgment-letter-page` | `acknowledgment_letter_page` | `clin/<clin_id>/acknowledgment-letter/` |
| `acknowledgment-letter-preview` | `preview_acknowledgment_letter` | POST AJAX; PDF via SharePoint Graph; no DB write; requires prior Save |
| `acknowledgment-letter-send-to-contract` | `send_acknowledgment_to_contract_folder` | POST AJAX; PDF to contract SharePoint folder; overwrites |
| `acknowledgment-letter-existing-pdf` | `get_existing_acknowledgment_pdf` | GET AJAX; load saved PDF from contract folder on page open; silent if missing |
| `acknowledgment-template-upload` | `upload_acknowledgment_template` | Staff only |
| `update_acknowledgment_letter` | `update_acknowledgment_letter` | AJAX save from letter page |

**Contract-level acknowledgment:** The acknowledgment section on `contract_management.html` is contract-level. `toggleAcknowledgment(field)` POSTs to `toggle_contract_acknowledgment` using `contract.id`. The PO Acknowledge Letter link navigates to `acknowledgment-letter-page` for `selected_clin.id`.

12. **Deprecated `api_add_note`** reads `request.content_type` (which is not set in AJAX requests). Any legacy call must pass `content_type_id` and `object_id` explicitly. No active in-app callers; the route remains for old bookmarks.

13. **There is no longer a standalone CLIN edit page.** CLIN field edits are handled by the Transactions edit modal (`openTransactionsEditModal`). Do not re-add a dedicated CLIN edit view or `/contracts/clin/<pk>/edit/` route without removing the Transaction wiring from `clin_detail.html` first.

14. **`IdiqContract` has no `company` FK.** Do not try to apply company-level SharePoint root overrides to IDIQ path resolution. Use `get_sharepoint_prefix()` directly for IDIQ folder patterns and root fallbacks.

15. **`documents_browser.html` payload key switches by mode.** The template uses `IS_DRAFT`, `IS_IDIQ`, and contract mode to choose auth params and Save Path payloads (`draft_id`, `idiq_id`, or `contract_id` plus `file_path`). If you change the browser payload shape, update all branches together.

16. **Inline `onclick` attributes on buttons inside delegated listener zones will silently kill those listeners in some browsers.** If a button has `onclick="event.stopPropagation();"` inline AND the same event is handled by a delegated listener on a parent element, the inline handler can throw or interfere before the delegated listener fires — leaving the button appearing dead with nothing in the console. **Rule: never use inline `onclick` on interactive elements inside a container that has a delegated click listener.** Instead, give the element a class (e.g. `.js-edit-btn`), handle it in the delegated listener with `e.target.closest('.js-edit-btn')`, and call `e.stopPropagation()` from inside that listener. See `reminders_popup.html` for the correct pattern.

17. **`window.__someBoundGuard` guards in scripts that run on page reload will prevent all listeners from registering after the first load.** The `window.__guard = true` pattern is only safe when scripts are injected into an existing DOM via `innerHTML` (where they could run multiple times in one page lifetime without a full reload). For standalone pages that reload normally (like `reminders_popup.html`), this guard causes the entire IIFE to exit on every reload after the first, silently removing all click handlers. Only use `window.__bound` guards in partials that are injected via `innerHTML` — i.e. `notes_popup_tab_panel.html` via `activateScriptsInNotesTabPanel`. Do not copy this pattern into standalone page scripts.

18. **`idiq_list` is a global (non-company-scoped) list view by design.** Do not add `ActiveCompanyQuerysetMixin` to it because `IdiqContract` has no company FK.

---

## 14. Safe Change Workflow

1. **Read `contracts/CONTEXT.md`** for feature context.
2. **Read the specific files** involved in your change (model, form, view, template, JS).
3. **Search repo-wide** for field names, URL names, and model imports before renaming anything.
   - `grep -r "contracts\." --include="*.py"` for model references
   - `grep -r "contracts:" --include="*.html"` for URL reversals
   - `grep -r "from contracts" --include="*.py"` for cross-app imports
4. **Check `transactions/`** if touching `Contract` or `Clin` fields.
5. **Check `processing/`** if touching fields that appear in the import/queue pipeline.
6. **Make minimal, scoped changes.** Avoid touching unrelated code in the same edit.
7. **Update all coupled files** (model + migration + form + template + admin + exports if relevant).
8. **Run migrations check:** `python manage.py makemigrations --check`
9. **Manually verify** the contract management page, CLIN form, and folder tracking load without errors.
10. **Verify cross-app:** open `processing` queue and `transactions` log to confirm they still function.

---

## 15. Quick Reference

### Primary files to inspect first
- `contracts/models.py` — all domain models
- `contracts/forms.py` — all forms and validation
- `contracts/urls.py` — all ~90 named URL patterns
- `contracts/views/contract_views.py` — core contract CRUD
- `contracts/views/mixins.py` — company-scoping enforcement

### Main coupled areas
- `Contract` ↔ `Clin` ↔ `ClinShipment` ↔ `PaymentHistory` (financial chain)
- `FolderTracking` ↔ `FolderStack` ↔ Excel export ↔ stack color constants
- `Note`/`Reminder` ↔ generic ContentType ↔ `notes_list.html` partial
- `ClinForm.clean()` ↔ `item_value`/`quote_value` auto-calculation
- `CompanyForm.save()` ↔ `UserCompanyMembership` sync

### Main cross-app dependencies
- `transactions` app: audit signals on `Contract`/`Clin` saves
- `processing` app: `QueueContract`/`QueueClin` mirror Contract/Clin schema
- `sales` app: tier-1 NSN scoring joins `contracts_*` in SQL Server view `dibbs_supplier_nsn_scored` (deployed via SSMS; see `sales/sql/dibbs_supplier_nsn_scored.sql`)
- `suppliers` app: `Supplier` model FKed from `Clin`
- `products` app: `Nsn` model FKed from `Clin` (PROTECT)
- `users` app: `request.active_company` middleware, `UserCompanyMembership`

### Main security-sensitive areas
- `ActiveCompanyQuerysetMixin` — multi-tenancy enforcement
- Superuser gates on `code_table_admin`, `company_views`, `admin_tools`
- Note/reminder owner checks
- Export endpoints (no public access)

### Riskiest edit types
- Renaming `Contract`/`Clin` fields (breaks `transactions` signals, `processing` queue, exports)
- Changing `FolderTracking.stack` choice values (stranded DB data)
- Weakening or removing `ActiveCompanyQuerysetMixin` (data leak)
- Using `queryset.update()` on `Contract`/`Clin` (skips audit trail)
- Changing `ClinForm.clean()` without understanding auto-calculated financial fields

## 15a. CLIN Fix Tool (Sunset)

The CLIN Fix tool (`/contracts/<pk>/clin-fix/`) is a temporary cleanup feature for reclassifying legacy `Clin` rows from the Access database into their correct destinations (`ContractPackaging`, `ContractFinanceLine`, `ClinShipment`, or hard-delete). It is **scheduled for removal**; treat it as scaffolding.

**Operational constraints:**

- The single **Fix Legacy CLINs** button in the Contract Line Items header on `contract_management.html` is the **only** allowed touch of any other page for this feature. Do not add context variables, banners, badges, navigation entries, or any other coupling that would propagate draft state.
- Draft awareness lives **only** on the CLIN Fix page itself (its "Unsaved CLIN Fixes" widget). Do not surface `ClinReclassificationDraft` counts on dashboards, the navbar, the lifecycle dashboard, or any other view. Other apps must not import either model.
- Server-side validation in `clin_fix_save` is authoritative — the eight rules there (existing packaging, income-side guards, parent-CLIN guards, multiple-packaging guard, delete-reason guard, batch-parent guard, finance-line-attachment guard, CLIN-on-contract guard) must run before any DB write. Client-side JS checks are UX hints only and should not be used to gate the save.
- All conversions for a contract commit inside a single `transaction.atomic()`. Do not refactor `clin_fix_save` to commit conversions one-at-a-time or to skip the upfront validation step — partial commits are a data-integrity hazard.
- Finance lines created here always attach to the **lowest-`item_number`** remaining CLIN on the contract that is not also being converted. Do not change the attachment target rule.
- Notes attached to a converted CLIN are moved to the contract via generic-relation `update()` after the `[Migrated from CLIN xxxx]` prefix is added (idempotent). `PaymentHistory` rows attached to the source CLIN are **hard-deleted** (the count is logged on the audit row). The original `Clin` row is hard-deleted last.
- Read-only audit log: `ClinReclassificationLog` is registered in the admin with `has_add_permission`, `has_change_permission`, and `has_delete_permission` all returning `False`. Keep it that way.
- Tests live in `contracts/tests/test_clin_fix.py`. Re-run when touching `clin_fix_views.py`, the migration, or any of the destination models the mapping reads (`ContractPackaging`, `ContractFinanceLine`, `FinanceLinePayment`, `ClinShipment`).

**Sunset removal checklist (when the cleanup is complete):**

1. Delete `contracts/views/clin_fix_views.py`, the import in `contracts/views/__init__.py`, and the 5 URL patterns in `contracts/urls.py`.
2. Delete `contracts/templates/contracts/clin_fix.html`, `contracts/static/contracts/js/clin_fix.js`, and the **Fix Legacy CLINs** button block on `contract_management.html`.
3. Delete `contracts/tests/test_clin_fix.py`.
4. Remove the `ClinReclassificationLog` / `ClinReclassificationDraft` model definitions and their admin registrations.
5. Create a migration dropping both tables (`contracts_clinreclassificationlog`, `contracts_clinreclassificationdraft`).
6. Repo-wide grep for `ClinReclassificationLog`, `ClinReclassificationDraft`, `clin_fix_page`, `clin_fix_save`, `clin_fix_draft_save`, `clin_fix_draft_delete`, and `clin_fix_parent_options` to verify nothing else references them.

---

## 16. Release Notes (Changelog) Rules

Product release notes are file-based. The markdown files are the **source of truth** (the DB is just a cache). When generating a release note, you MUST adhere to these strict validation rules, or the system will skip the file on deployment.

- **File Path & Naming:** `release_notes/YYYY-MM-DD-short-slug.md`
- **Body:** Must be valid Markdown and non-empty. 
- **Frontmatter (Required):** You must include a YAML frontmatter block exactly like this:

```yaml
---
id: 2026-05-11-short-slug      # CRITICAL: Must exactly match the filename stem (without .md)
title: Human-readable title
published: false               # Always default to false on dev branches; set true when ready to ship
publish_date: 2026-05-11       # Must be an ISO date
tags: [improved, contracts]    # CRITICAL: Must be a list of EXACTLY TWO strings (see taxonomy below)
critical: false                # Must be a boolean
---

```

**Strict Tag Taxonomy:**
The `tags` array will fail validation if it does not contain exactly two items:

1. **One Change Type:** `new`, `improved`, `fixed`, OR `breaking`
2. **One Area:** `contracts`, `finance`, `sales`, `training`, OR `system`
*(Do not invent new tags. Unknown tags cause the file to be skipped.)*

---

## 17. Supplier Payment Forecast Rules & Safety Constraints

- **Read-derived Planning Window**: The forecast page is purely a planning overlay window, not a system of financial record. All cash and formal payment data must continue to reside in and derive from `quote_value` / `paid_amount`.
- **Single Payment Recording Path**: Never create a new or secondary payment-recording path. Supplier payments are recorded exclusively through the existing `payment_history_api` and `_recompute_clin_payment_rollup` flow by reusing the `partial-value-cell` component.
- **No Fabricated Due Dates / Date Floor**: A payment term with `net_days = NULL`, or a missing target date (including any sentinel date before `MIN_REAL_DATE = date(2015, 1, 1)`), must always produce a flagged row in the "Needs Attention" bucket. Do not invent due dates, and do not process shipments/targets that have sentinel migration dates.
- **Whitelist Scope**: The forecast must whitelist open contracts specifically (using `LIVE_STATUSES = ["Open"]`) rather than excluding canceled/closed statuses via a blacklist, to ensure the page remains clean and scoped to active operations.
- **No Data Migration for Code Tables**: Never populate `net_days` values in a data migration. Code table values (like COS=0, Net 30=30, etc.) are developer-managed directly via the code-table admin interface.
- **Audit Exclusion for Planning Metadata**: The fields of the `ShipmentPaymentPlan` model store planning intentions, not financial state. They must never be added to `transactions.signals.TRACKED`.
- **No `queryset.update()` on Audited Fields**: For any audited data mutations (such as changing the payment term `<select>`), perform instance-level `.save(update_fields=[...])` so that the `transactions` signals capture and record the history change.


```
