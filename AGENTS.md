# AGENT.md — Backyard Marauder rules for AI sessions

- Never wire Marauder into `arcade/registry.py`, `arcade/puzzles/`, or
  `ArcadeAttempt`.
- Never modify Wordle, Nonogram, or Lights Out code when working on Marauder.
- Never copy leaderboard ordering logic between `ArcadeAttempt`
  (lower-is-better) and `MarauderRun` (higher-is-better).
- `CHECKSUM_FIELDS` in `services_marauder.py` and the joined array in
  `net.js::submitRun` must change in the same commit or every submission
  returns 403.
- Constants marked `[SERVER]` in `const.js` must change in the same commit as
  their mirrors in `services_marauder.py`.
- Do not change the Marauder signing salt without accepting that every
  in-flight run token dies on deploy.
- Edit unapplied `0004_marauder.py` in place; do not generate a `0005_*`
  migration unless `0004` has already been applied in the target environment.
- Nothing in the Marauder subsystem may import from the puzzle framework.
  The only allowed coupling is `lobby()` importing `get_global_top`.

## Quote — Supplier Research (when touching `quote/services/supplier_research.py`)
- Use `dibbs_award` by CAGE only; do not use `dibbs_we_won_awards`.
- Do not read `SupplierNSNCapability` / `supplier_nsn_capability`.
- Excel NSN / CAGE / contract cells must be text (`'@'`).
- Service layer returns materialized lists, not querysets.
- The page view is a shell and must not call service functions; data loads via
  `supplier_research_panel`. Honor `?refresh=1` on the `sam` panel only.
- All award reads go through `_award_queryset()` (excludes `is_faux=True`). Dedupe with
  `.values(*AWARD_DEDUPE_FIELDS).distinct()`; never count or sum raw rows.
- Freshness is `Max(posted_date)` with `posted_date <= today` — never `award_date`.
- MSSQL: every `order_by` field on a `.distinct()` query must also be in its `.values()` list.
- **MSSQL 2,100-parameter limit:** never pass an unbounded list to `__in`. Chunk it (see
  `NSN_IN_CHUNK = 500` in `supplier_research.py`, `IN_CHUNK` in `matching.py`), materialize each
  chunk, and merge in Python.
- `get_open_solicitations` is read-only: no writes to quote / dibbs / supplier tables, and no calls
  into `matching.py` / `capabilities.py` functions that write. NSN comparison goes through
  `nsn_query_variants()`. Est. Value comes from `queue.latest_unit_costs`, never a new price lookup.
  "Open" is `return_by_date >= today` only.
- `get_sam_entity` has three states (`ok` / `not_found` / `error`); a failed lookup must never
  render as "no record found".

## DFAS payment receipts (when touching `contracts/services/dfas_receipts/`)
- One pipeline: `process_message`. The live task and the backfill command both call it.
- The mailbox write is always last. Save the SharePoint item id before any PATCH or move.
- Never upload to a documents-root fallback folder. Never use `send_pdf_bytes_to_folder`.
- `normalize_piid` slices on length only. Do not strip a `P` with a regex.
- No company scoping on the contract lookup. Never write `Contract`, `IdiqContract`, `PaymentHistory`, or `files_url`.

## IDIQ contracts (when touching `IdiqContract` create / edit / close / delete)
- IDIQ numbers are compared via `normalize_idiq_number` (Python) / `idiq_number_expression` (ORM) in
 `contracts/services/contract_number.py`. Never add another IDIQ number normalizer.
- Every IDIQ create or rename must go through `find_duplicate_idiq` (closed IDIQs count).
- Delete is blocked while `get_idiq_dependents(idiq)` is non-empty. `ScannedFolder` is the only
 model in `IDIQ_DEPENDENT_EXEMPT_MODELS`; do not add user-entered data to that list.
 `Contract.idiq_contract` is CASCADE; never add a delete path that skips this check.
 Delete / Close / Reopen are POST-only.
- Do not add a DB unique constraint on `IdiqContract.contract_number` until `find_duplicate_idiqs`
 reports 0 groups in production.
- IDIQs appear in Contract search (`contracts:contract_search`) only via `search_idiq_contracts` in
 `contracts/services/idiq_search.py`. Match through `normalize_idiq_number` / `idiq_number_expression`.
 Never `union()` IDIQs with contracts. Keep the delivery-order count a subquery (a join + GROUP BY on
 the number expression breaks on MSSQL). Keep the JSON `results` key: three pages read `data.results || data`.

## POD complete (when touching CLIN pod status or `Clin.pod_complete`)
- Status is only `compute_pod_status` in `contracts/services/pod_status.py`. Never compute `pod_status` inline.
- `pod_complete` true → `"full"`. Otherwise `"none"` when no shipment has a `pod_date` (including zero shipments); otherwise `"partial"`.
- `Clin.pod_complete` is `BooleanField(default=False)` (not null, no index). `Clin.pod_date` stays the MAX rollup.
- Check guard is server-side on `clin_pod_complete_api` only: at least one shipment and every `pod_date` non-null. Uncheck is always allowed. `ship_qty < order_qty` (both non-null) still saves and returns `qty_warning`.
- Auto-uncheck lives only in `_sync_clin_ship_fields`. Never write `pod_complete` anywhere else, and never add it to `ClinForm`.
- Endpoint: `POST /contracts/api/clin/<id>/pod-complete/` (`contracts:clin_pod_complete_api`). CSRF stays on.
- Shipments popup is `GET /contracts/clin/<id>/shipments-popup/` (`clin_shipments_popup`). Money columns are display-only. Create may post `paid_amount` and `wawf_payment` when non-blank. Never post `quote_value` or `item_value`. Edits post logistics fields only through `update_shipment` via instance `.save()`. Today buttons use local date parts, never `toISOString()`. `?add=1` and `?edit=<id>` open the single `#shipmentModal` (add, or edit when the id belongs to this CLIN). The popup strips those params with `history.replaceState`. `data-name` is the raw stored name. CLIN detail rows are read-only and Edit opens the popup. `Clin.pod_date` is locked when shipments exist, in the UI and in `transaction_edit_field`. `add_partial_shipment` wraps create, ledger, rollup, and sync in one `transaction.atomic()`. Host buttons use `js-open-clin-shipments-popup` and `data-popup-url`. The visible label is `Manage shipments` on Finance Audit, the contract-management CLIN card, and CLIN detail (popup list URL, no `?add=1`). Leave `#shipmentsModal`, `openShipmentsModal`, `get_clin_shipments`, `add_partial_modal.*`, and `complete_clin_shipping` in place until Stage 6. Blank shipment labels are built only by `label_shipments` in `contracts/services/shipment_labels.py` (entry order). `update_shipment` re-derives `quote_value` / `item_value` from the CLIN prices when `ship_qty` changes, and never assigns `paid_amount` or `wawf_payment`.
- Finance Audit POD Date is the column immediately after Ship Qty. Every CLIN-table `<tr>` must still match the header column count, counting `colspan`. The opener sets `window.__clinShipmentsDirty` from `window.onClinShipmentsChanged` and reloads once when `clinShipmentsPopup` closes.

## Shipment payments (when touching shipment or CLIN Paid / Customer Pay)
- Use `contracts/services/shipment_payments.py`; never write CLIN Paid / Customer Pay on a CLIN with shipments. Full rules: `contracts/AGENTS_contracts.md`. `transaction_edit_field` serves only `EDITABLE_FIELDS` (`transactions/AGENTS_transactions.md`).

## CSS (when touching `static/css/app-core.css` or any date field)
- Date inputs use the native browser calendar indicator only. Never add a
  background-image calendar icon or an `input-group-text` calendar icon next to a
  `type="date"` input.

## Inventory public API (when touching `inventory/api/` or `inventory/selectors.py`)
- The API serializes only `id`, `nsn`, `description`, `part_number`, `manufacturer`, `quantity` via
 `serialize_public_item`. Never expand that allowlist without review. Never expose price, cost, or
 location columns. Never use `model_to_dict` or an all-fields `values()`.
- Only `is_public=True` rows, via `public_items_queryset()`. It never searches the location column.
- Auth mirrors `suppliers/portal/auth.py` (same canonical string, 300 s window, 401 body shape) but
 uses `INVENTORY_API_KEY` / `INVENTORY_API_HMAC_SECRET`. Do not import from `suppliers.*`.
- No CORS headers. Every API response sends `Cache-Control: no-store`.
- The `LoginRequiredMiddleware` bypass is the exact prefix `/api/inventory/v1/`. Do not widen it.