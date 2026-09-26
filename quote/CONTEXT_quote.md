# Quote Context

## 1. Purpose
The `quote` app owns the whole human DIBBS quoting workflow and **all of its
data**: solicitation pipeline state, supplier NSN/FSC capabilities and matching,
RFQ dispatch, the shared `quotes@` mailbox, supplier quotes with landed-cost
buildup, bid staging, the BQ export, and post-award win/loss analytics ("Our Bids").

It does **not** ingest DIBBS files or awards — the `dibbs` app does. `quote`
reads `dibbs` tables, never writes them, and reacts to
`dibbs.signals.import_completed`. See §11.

Functional spec and the two approved UI mockups live in `quote/docs/`:
`Quote.md`, `Mailbox Workflow - OptionB.html`, `Our Bids Post-Award Intelligence.html`.

## 2. App Identity
- **Django app name:** `quote` — `QuoteConfig` (`quote/apps.py`), verbose name
  "Quotes (DIBBS Quoting)". `ready()` imports `quote/signals.py` to connect receivers.
- **URL prefix:** `/quote/`, namespace `quote:`.

## 3. High-Level Responsibilities
- Workflow state per solicitation (`QuoteSolicitation`) and supplier matching
  (`QuoteSupplierNSN`, `QuoteSupplierFSC`, `QuoteSolicitationMatch`).
- RFQ ledger (`QuoteRFQ`), supplier quotes (`QuoteSupplierQuote`), staged bids
  (`QuoteBid`), inbound email (`QuoteEmail`, `QuoteEmailAttachment`,
  `QuoteEmailSolLink`), post-award reconciliation (`BidOutcome`).
- Reads solicitations, lines, approved sources, awards, `CompanyCAGE`, SAM cache
  from `dibbs`; suppliers/packhouses from `suppliers`; part dimensions from
  `products.Nsn`.

## 4. Key Files
| File / Directory | Responsibility |
|---|---|
| `apps.py` | `QuoteConfig`; `ready()` connects `signals.py`. |
| `signals.py` | `import_completed` receiver → `services.matching.process_import_batch`. |
| `urls.py` | `app_name = 'quote'` — **must stay exactly `'quote'`** (permission middleware keys on it). |
| `models/base.py` | App-scoped abstract `AuditModel`. |
| `models/solicitation.py` | `QuoteSolicitation` (`quote_solicitation`) — OneToOne on `dibbs.Solicitation` (`related_name='quote_state'`). Status `UNMATCHED → MATCHED → RFQ_SENT → QUOTING → BID_READY → BID_SUBMITTED`, plus `NO_BID`, `ARCHIVED`. 20-minute review claim (`claim_for`, `is_claimed_by_other`). |
| `models/matching.py` | `QuoteSupplierNSN` (`quote_supplier_nsn`, 13-digit NSN), `QuoteSupplierFSC` (`quote_supplier_fsc`), `QuoteSolicitationMatch` (`quote_solicitation_match`) — one row per (solicitation, supplier, source ∈ NSN/FSC/MANUAL). |
| `models/rfq.py` | `QuoteRFQ` (`quote_rfq`) — one row per (line, supplier). `QUEUED → READY_TO_SEND → SENT → RESPONDED`, plus `NO_RESPONSE` / `DECLINED`. |
| `models/quotes.py` | `QuoteSupplierQuote` (`quote_supplier_quote`) — cost, both adders, packhouse FK, markup, `final_government_unit_price`, `is_selected_for_bid`, `source_email` FK back to the reply it was typed from. `landed_unit_cost` is Decimal-only. |
| `models/bids.py` | `QuoteBid` (`quote_bid`) — OneToOne on `dibbs.SolicitationLine`; the solicitation is reached via `line.solicitation` (no duplicate FK). Every BQ overlay column + `clin_group`. |
| `models/email.py` | `QuoteEmail` (raw payload, headers, claim), `QuoteEmailAttachment` (bytes), `QuoteEmailSolLink` (many-to-many email ↔ line). |
| `models/outcomes.py` | `BidOutcome` — OneToOne on `QuoteBid`, nullable FK to `dibbs.DibbsAward`, derived deltas, frozen bid snapshot. |
| `services/matching.py` | `seed_solicitation_states`, `match_solicitations`, `process_import_batch`, `normalize_nsn`. |
| `services/graph_inbox.py` | Graph reader for the `GRAPH_MAIL_SENDER_RFQ` mailbox (moved from the retired `sales` app). |
| `management/commands/seed_quote_demo.py` | Dev-only demo data (§14a). |
| `templates/quote/base.html` | App shell (`.app-shell` / `.app-subnav`, shared with `dibbs`). |

## 5. Data Model Notes
- Every table has an explicit `quote_` `db_table`. Money: unit prices `Decimal(13,5)`,
  totals `Decimal(15,2)`, percentages `Decimal(5,2)`.
- `QuoteSolicitation` and `QuoteSolicitationMatch` set `dibbs_disposable = True`:
  they are auto-created, so dibbs' import-batch delete may cascade through them.
  Anything a rep creates (RFQs, quotes, bids, email links) blocks that delete.
- Matching is additive and idempotent; it only moves `UNMATCHED → MATCHED` and
  never rewinds a worked solicitation (`MATCHING_STATES`).
- `QuoteBid.line` is OneToOne → Split-CLIN is native; Combined mode shares `clin_group`.
- `BidOutcome.award_unit_price` is **derived** (`award_total_price / award_quantity`);
  DIBBS publishes neither quantity nor unit price. Always label it derived.

## 6. Request / User Flow
Currently `/quote/` (placeholder dashboard) only. Phase 1–4 screens from
`quote/docs/Quote.md` are not built yet. Behind the scenes, every DIBBS import
seeds `QuoteSolicitation` rows and runs matching.

## 7. Templates and UI
- Bootstrap 5.3.3 (Spacelab) from the global base. New classes go in
  `static/css/app-core.css`. No new CSS files, no Tailwind, no CDN tags.
- Dark mode: `[data-bs-theme="dark"] .class`. Drawers: `offcanvas-end`;
  modals: `bootstrap.Modal`; toasts: `window.showToast`.
- Mockups in `quote/docs/` are IA references only (they hardcode a dark palette).

## 8–10. Admin, Forms, Services
- `admin.py` registers nothing yet.
- Business logic belongs in `quote/services/`. Planned: a single Decimal-only
  cost-buildup service and the BQ writer.
- **BQ writer reference:** the retired `sales/services/bq_export.py` (git history,
  commit `c92e273`) overlaid bid fields onto `SolicitationLine.bq_raw_columns`
  (1-based cols): 6 quoter CAGE, 7 quote-for CAGE, 13 SB rep, 21 affirmative
  action, 22 previous contracts, 23 ADR, 24 bid type, 25 payment terms,
  50 unit price, 51 delivery days, 65 hazmat, 67 material, 102 mfr/dealer,
  103 mfg CAGE, 106–108 part-number offered code/CAGE/P/N, 120 child labor,
  121 remarks. Header defaults (13, 21–23, 120) come from `dibbs.CompanyCAGE`.

## 11. Cross-App Dependencies
### Reads (never writes)
- `dibbs`: `Solicitation`, `SolicitationLine` (incl. `bq_raw_columns`),
  `ApprovedSource`, `DibbsAward`, `CompanyCAGE`, `SAMEntityCache`,
  `NsnProcurementHistory`.
- `suppliers`: `Supplier` (incl. `is_packhouse`), `Contact`.
- `products.Nsn` — **one sanctioned write**: the freight sub-modal may update
  `unit_weight`, `unit_length`/`unit_width`/`unit_height`,
  `dimension_source_notes`, `dimensions_last_verified`. Nothing else.

### Reusable services
- `mailer.services.graph_mail.send_mail_via_graph(...)` — GCC High only; returns
  `False` on failure, never raises.
- `quote.services.graph_inbox` — `fetch_inbox_messages()`, `fetch_message_body(id)`,
  `mark_message_read(id)`. On demand, not polled.
- `dibbs.services.competitor_stats.get_competitor_stats()` — canonical; do not duplicate.
- Packhouse lookup: `Q(is_packhouse=True) | Q(supplier_type__description__iexact='packhouse')`
  as a sort hint, not a filter.

### Apps that depend on `quote`
- `core` global search (supplier ↔ solicitation hops via `QuoteSolicitationMatch`, `QuoteRFQ`).
- `products` NSN / supplier pages (`QuoteSupplierQuote`, `QuoteBid`, `QuoteSupplierNSN`).

## 12. URL Surface
| Name | Path | View |
|---|---|---|
| `quote:dashboard` | `/quote/` | `views.dashboard` |

## 13. Permissions / Security
- `@login_required` on every view.
- `AppRegistry`: `quote/0002` created a `quote` row (deny-by-default) and granted it
  to users who had `sales` access. **Non-superusers need an explicit
  `AppPermission(has_access=True)`** — there is no auto-grant signal.
- No `company` FK on quote data; scope by CAGE via `dibbs.CompanyCAGE`.
- `QuoteEmail.body_html` is supplier HTML: render only in a sandboxed no-scripts iframe.

## 14. Background Work
- `import_completed` receiver (synchronous, inside the import request / WebJob).
- Planned: `quotes@` mailbox poller, nightly `BidOutcome` reconciliation, 7-day
  unmatched archival. Each needs a `quote/tasks/` callable + `TASK_FUNCTIONS` entry +
  `ScheduledTask` data migration.

## 14a. Demo Data (dev only)
`python manage.py seed_quote_demo` seeds ten solicitations across every stage
(unmatched, matched, RFQ queued/sent, six bid-submitted → 2 won / 3 lost /
1 pending, two losses within 5%), with `QuoteSolicitation` state, capabilities
and matches. `--clear` / `--list`. Refuses to run in production. Every row is
tagged (import batch `imported_by`, `DEMO-SEED-` notice/message ids, supplier
notes marker, NSN `dimension_source_notes` marker) and it never modifies a
pre-existing `contracts_nsn` row.

## 15. Testing
`test_scaffold.py` (wiring, table prefixes, FK targets, landed cost, auto-award
gate, claims, RFQ uniqueness, templates), `test_matching.py` (import signal →
state seeding, additive matching, idempotency, no rewind, receiver isolation,
batch-delete protection), `test_permission_seed.py`, `test_seed_quote_demo.py`.
Run `python manage.py test quote dibbs`.

## 16. Migrations
- `0001_initial` — seven original `quote_*` tables (FKs retargeted to `dibbs`).
- `0002_seed_app_registry_and_permissions`.
- `0003_solicitation_state_and_matching` — adds `QuoteSolicitation`, capability and
  match tables, `QuoteSupplierQuote.source_email`; drops `QuoteBid.solicitation`.
- `0004_backfill_solicitation_state` — one set-based `INSERT … SELECT` giving every
  existing solicitation a state (past due → `ARCHIVED`, else `UNMATCHED`).
- `products/migrations/0005` added the NSN dimension provenance fields.

## 17. Known Gaps
1. `Quote.md` pre-flight item 1: treat BQ rows as **121** columns; prove with a
   byte-level diff against a DIBBS-accepted `bq` file.
2. Whole-file BQ round-trip is impossible today — the downloaded file isn't kept.
3. Real-time "another rep is reviewing" needs no websockets: claim fields +
   self-scheduling `setTimeout` poll.
4. Quote.md "margin" presets (2/4/6%) are undefined as markup-on-cost vs margin-on-
   price; the demo seeder uses markup. Decide before building the cost service.
5. The "Supplier always requires external packaging" toggle has no quote-owned home yet.

## 20. CSS
Three files repo-wide: `theme-vars.css`, `app-core.css` (shared `.app-shell` /
`.app-subnav` live under the "App shell + sub-nav" banner), `utilities.css`.
