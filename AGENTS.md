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

## CSS (when touching `static/css/app-core.css` or any date field)
- Date inputs use the native browser calendar indicator only. Never add a
  background-image calendar icon or an `input-group-text` calendar icon next to a
  `type="date"` input.
