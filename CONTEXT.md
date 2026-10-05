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
