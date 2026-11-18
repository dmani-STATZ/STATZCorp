# CONTEXT.md — Backyard Marauder (arcade real-time subsystem)

## Backyard Marauder

Marauder is a real-time vertical shooter inside the `arcade` app, deliberately
outside the daily-puzzle framework (`registry.py` / `PuzzleGame` / `ArcadeAttempt`).
It must never be wired into that engine. The only permitted coupling is one-way:
`arcade/views.py::lobby()` imports `get_global_top()` from
`arcade/services_marauder.py` to render the lobby card.

Its models are `PilotProfile` and `MarauderRun`. **`MarauderRun.score` is
higher-is-better**, the inverse of `ArcadeAttempt.score` (lower-is-better).
Separate tables, separate services, separate templates.

Two leaderboards, both top-5:
- Global — all pilots, all time (`get_global_top`)
- Personal — one pilot's own best runs (`get_user_top`)

`arcade/services_marauder.py` is contractually coupled to
`static/arcade/js/marauder/const.js`. Constants marked `[SERVER]` in `const.js`
are mirrored there; changing one without the other causes honest runs to be
flagged.

Anti-cheat is layered deterrence, not prevention:
- Salted signed session token (namespace `arcade.marauder.v1`)
- Integrity checksum keyed by that token
- Plausibility bounds derived from client tunables
- Unique one-shot seeds (`MarauderRun.seed` UNIQUE)

**Phase 1 status: complete** (foundation + difficulty/scoring correction,
missing service module, salt isolation, unique seed, director ramp).

**Phase 2 outstanding:** replay-guard wiring in `views_marauder.py`,
`IntegrityError` → 409, rate limiting on `run_start`.

---

## Supplier Research (`quote` app)

**Purpose:** One-page CAGE lookup for sales: STATZ supplier match, cached SAM.gov entity,
approved-source rows, and full DLA award history, plus a three-tab Excel download.

**URLs (namespace `quote:`):**
- `GET /quote/research/?cage=XXXXX` — `supplier_research` (shell only: validates the CAGE, renders
  four spinner cards, runs **no** queries)
- `GET /quote/research/<cage>/panel/<status|sam|sols|awards|approved>/` — `supplier_research_panel`
  (server-rendered HTML fragment; 400 bad CAGE, 404 unknown panel). `status` is the small badge in
  the page header; the cards are SAM.gov Entity → Open Solicitations → Award History → Approved Sources.
- `GET /quote/research/<cage>/export/` — `supplier_research_export`

**Panel architecture:** `static/quote/js/supplier_research.js` fetches all four panels in parallel,
so each card fills in on its own (a slow SAM lookup no longer blocks the rest). 60 s abort,
per-panel Retry, and a redirect/non-OK guard so a login page is never injected into a card.
`?refresh=1` is honored on the `sam` panel only (`get_or_fetch_cage(force_refresh=True)`).

**Open Solicitations panel (`sols`):** open DIBBS solicitation lines (`return_by_date >= today`,
no workflow-status filter) whose NSN is an approved-source NSN for the CAGE, an NSN it has won
before (non-faux `DibbsAward`), or a `QuoteSupplierNSN` capability of a STATZ `Supplier` with that
CAGE. NSNs go through `nsn_query_variants()` and are looked up in chunks of `NSN_IN_CHUNK = 500`.
Est. Value reuses `quote.services.queue.latest_unit_costs` (qty × latest DLA unit price). Strictly
read-only; surfacing approved-source matches here does not make them an automatic match source in
the queue (Known Gap #7 stands). Excel adds an `Open Solicitations` sheet built at export time.

**Data sources (read-only):**
- Existing supplier — `suppliers.Supplier.cage_code` via `find_existing_supplier()`
- SAM.gov — `dibbs.services.sam_entity.get_or_fetch_cage()` only (`get_sam_entity()`), returning
  `state` = `ok` / `not_found` (`raw_json['found']` is not True) / `error` (`fetch_error=True` or
  an exception). Errors are never shown as "not found" and can be retried.
- Approved sources — `dibbs.ApprovedSource` / `tbl_ApprovedSource` by `approved_cage`,
  de-duplicated on (nsn, part_number, company_name); no CAGE column (`get_approved_sources()`)
- Awards — `dibbs.DibbsAward` by `awardee_cage`, not `dibbs_we_won_awards`
  (`get_award_summary()`, `get_awards()`). `is_faux=True` rows (placeholders made when a MOD
  arrives before its award; invented `YYYY-09-30` dates, no price) are excluded everywhere.
  Rows identical on `AWARD_DEDUPE_FIELDS` collapse to one. "Award data current through" is
  `Max(posted_date)` where `posted_date <= today`, never `award_date`.

**Access:** Same as the rest of Quotes — `@login_required` on views plus
`LoginRequiredMiddleware` / `users.AppPermission` for the `quote` app registry row.

**Stage 4 status:** Live DIBBS lookup deferred; page uses local tables and SAM cache only.

---

## DFAS Payment Receipt Filing (`contracts` app)

DFAS payment notices in the finance@ mailbox are filed as PDFs in the matching contract's SharePoint folder. The background task is `file_dfas_receipts` (15 minutes, `run_order` 11). It does nothing unless `DFAS_RECEIPTS_ENABLED=true`.

In-scope mail is from `disa.ogden.eis.mbx.wawfnoreply@mail.mil` with subject `Notification of new DFAS payment action` (no FW:/RE:). The live job reads Inbox only. Filed messages are marked read and moved to `Inbox/WAWF/DFAS Receipts`. Unmatched messages are marked unread and moved to `Inbox/WAWF/Unmatched`.

`DfasPaymentNotice` records the parse and the SharePoint item. Contract data is read-only, and the lookup is not company-scoped. `python manage.py dfas_receipts_backfill` is a dry run; add `--apply` to write. Drag an unmatched email back to the Inbox, or pass `--folder "Inbox/WAWF/Unmatched" --apply`, after the contract or folder is fixed.

---

## IDIQ Duplicate Guard + Safe Close / Delete (`contracts` app)

**Duplicate guard.** IDIQ numbers are compared with `normalize_idiq_number()` in `contracts/services/contract_number.py` (trim, drop every `-` and space, uppercase). Its ORM twin `idiq_number_expression()` is used for lookups. `find_duplicate_idiq()` in `contracts/services/contract_create.py` checks every IDIQ, closed ones included. It runs in `create_idiq_from_payload` (Intake finalize, raises `ContractCreationError`) and in `IdiqContractForm.clean_contract_number` (edit, excludes the record itself). There is no DB unique constraint; existing duplicates would break one.

**Delete rules.** `get_idiq_dependents(idiq)` in `contracts/models.py` returns `(label, count)` for every reverse relation (`_meta.related_objects` plus the `notes` GenericRelation) except `IDIQ_DEPENDENT_EXEMPT_MODELS`, which is `ScannedFolder` only. Those rows are scanner snapshots with `on_delete=SET_NULL`; deleting the IDIQ unlinks them and leaves the folder. Delivery orders, NSN/supplier pairs, notes, and scan filing logs still block. `IdiqContractDeleteView` is POST-only and deletes only when that list is empty. `Contract.idiq_contract` is `CASCADE`, so this guard is the only thing stopping a delete from wiping delivery orders. Close and Reopen are POST-only views (`idiq_contract_close` / `idiq_contract_reopen`). The edit form no longer has a `closed` field.

**Audit.** `IdiqContract` edits (including `closed`) are in `transactions.signals.TRACKED`. Create and delete write one `Transaction` row on `contract_number` via `record_lifecycle_transaction`.

**Report.** `python manage.py find_duplicate_idiqs` is read-only. It lists every group of IDIQs sharing a normalized number with pk, status, created date, drive item flag, and dependent counts.

**Contract search.** `contract_search` (`/contracts/search/`, JSON) also returns IDIQs from `search_idiq_contracts()` in `contracts/services/idiq_search.py`. Matching is `idiq_number_expression()` contains `normalize_idiq_number(query)`, scoped to the active company. Closed IDIQs are included (the contract search has no open/closed filter). Max 25 rows, exact match first, then number; `idiq_total` is the uncapped count. Delivery-order counts come from a subquery, not a join + GROUP BY. There is no `union()` across models. The response is `{results, idiqs, idiq_total, idiq_limit}`; every contract row has `idiq` (`None` or `{id, contract_number, url}`) read through the `idiq_contract` join. The Jump to Contract modal (`contract_base.html`) and the lifecycle dashboard box render an IDIQ panel above the contract rows. The DFAS review picker reads `results` only.

---

## POD complete (`contracts` app)

`Clin.pod_complete` is a stored boolean (`default=False`, not null, no index). `Clin.pod_date` is still the MAX of non-null shipment `pod_date` values. Status strings `none` / `partial` / `full` come only from `compute_pod_status` in `contracts/services/pod_status.py`: the flag true means `full`; otherwise `none` when no shipment has a POD date (including zero shipments); otherwise `partial`.

Checking the flag (`POST /contracts/api/clin/<id>/pod-complete/`, name `clin_pod_complete_api`) requires at least one shipment and a POD date on every shipment. Unchecking is always allowed. A short ship quantity (`ship_qty < order_qty`, both set) still saves and returns `qty_warning`. If the flag is on and a shipment change leaves zero shipments or any null `pod_date`, `_sync_clin_ship_fields` clears it. That function and the endpoint are the only writers. Do not compute pod status inline, and do not add `pod_complete` to `ClinForm`.

After deploy, run the hand-run TSQL backfill in `contracts/CONTEXT_contracts.md` (Step 0a, then Step 0b). It is not a Django migration.

The shipments page (`clin_shipments_popup`) is the only place a shipment is added, edited, or deleted. It opens from Finance Audit (POD Date column immediately after Ship Qty, plus a Manage shipments button beside + cost), from the contract management CLIN card, and from CLIN detail's Manage shipments button (list view) or row Edit (`?edit=<id>`). One Add/Edit modal handles both. Money columns on the popup are display-only. Create may send `paid_amount` and `wawf_payment` when those fields are filled, and may send `pod_date`. Quote and item values are derived and are not posted. Edits send logistics fields only through `update_shipment`, which re-derives quote and item value when the quantity changes. CLIN detail shipment rows are read-only. `Clin.pod_date` is locked when the CLIN has shipments. Creating a shipment and its ledger rows is one database transaction. The popup tells the opener via `window.onClinShipmentsChanged`. Finance Audit and CLIN detail set a dirty flag and reload once when the popup closes. Contract management refreshes the selected CLIN card in place. Today buttons use the local calendar date, never `toISOString()`. Every row in the Finance Audit CLIN table has to keep the same column count as the header. The old shipments modal, add-partial modal, and `complete_clin_shipping` stay in the code until Stage 6. Blank shipment labels come only from `contracts/services/shipment_labels.py` (entry order).

Payment source of truth (Stage 7a): on a CLIN with shipments, Paid / Customer Pay live on the shipments and change only through `contracts/services/shipment_payments.py`; see "Payment source of truth" in `contracts/CONTEXT_contracts.md` and the `EDITABLE_FIELDS` allowlist in `transactions/CONTEXT_transactions.md`.

Shipment payment dates (Stage 8): `ClinShipment.paid_date` / `wawf_payment_date` roll up (MAX, never NULL-over) to `Clin.paid_date` / `wawf_recieved`; see "Shipment payment dates" in `contracts/CONTEXT_contracts.md`.

---

## Inventory Dashboard + Public Inventory API (`inventory` app)

**Dashboard.** `/inventory/` is server-side: search (`q`), visibility (`vis` = `all|public|private`), whitelisted sort (`sort`, `dir`), pagination (`page`, `per_page` in 25/50/100). Query logic lives in `inventory/selectors.py` (`build_item_queryset`, `inventory_kpis`). KPI cards come from one `aggregate()` over the whole table. JS is `inventory/static/inventory/js/inventory_dashboard.js`; no inline scripts.

**Public API.** `GET /api/inventory/v1/items/` and `/items/<pk>/` (`inventory/api/`, namespace `inventory_api`) serve `statzcorp-com` server-to-server. Same HMAC scheme as the supplier portal API, separate secrets `INVENTORY_API_KEY` / `INVENTORY_API_HMAC_SECRET`; unset secrets fail closed (401). Only `InventoryItem.is_public=True` rows, and only `id, nsn, description, part_number, manufacturer, quantity`. `/api/inventory/v1/` is in the `LoginRequiredMiddleware` public URL list (`STATZWeb/middleware.py`). Consumer contract: `inventory/INVENTORY_API.md`.