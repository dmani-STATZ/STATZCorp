# Quote Context

## 1. Purpose
The `quote` app owns the human DIBBS quoting workflow: reviewing matched solicitations,
dispatching RFQs to suppliers, capturing supplier replies from the shared `quotes@` mailbox,
building landed cost (supplier cost + packaging adder + freight adder + markup), staging bids,
exporting the DIBBS BQ batch file, and post-award win/loss analytics ("Our Bids").

It does **not** ingest DIBBS files. Ingestion, supplier matching and award ingestion stay in
`sales`. The `quote` app reads those tables and never writes them. See §11.

Functional spec and the two approved UI mockups live in `quote/docs/`:
`Quote.md`, `Mailbox Workflow - OptionB.html`, `Our Bids Post-Award Intelligence.html`.

## 2. App Identity
- **Django app name:** `quote`
- **AppConfig:** `QuoteConfig` (`quote/apps.py`), label `quote`, verbose name "Quotes (DIBBS Quoting)"
- **Filesystem path:** `/quote`
- **URL prefix:** `/quote/`, namespace `quote:`
- **Role:** Feature app implementing the quoting to bid to export to post-award lifecycle on top of
  the solicitation data `sales` ingests.

## 3. High-Level Responsibilities
- Own the RFQ dispatch ledger (`QuoteRFQ`), supplier quotes with full cost buildup
  (`QuoteSupplierQuote`), staged bids (`QuoteBid`), inbound email + attachments
  (`QuoteEmail`, `QuoteEmailAttachment`, `QuoteEmailSolLink`) and post-award reconciliation
  (`BidOutcome`).
- Read solicitations, lines, approved sources, supplier capability tiers and awards from `sales`.
- Read the supplier directory (including packhouses) from `suppliers`, and part dimensions from
  `products.Nsn`.
- Write the BQ submission file from `SolicitationLine.bq_raw_columns` with the full pre-flight
  validation set Quote.md specifies.

## 4. Key Files and What They Do
| File / Directory | Responsibility |
|---|---|
| `apps.py` | `QuoteConfig`, label `quote`. |
| `urls.py` | `app_name = 'quote'`. **Must stay exactly `'quote'`** — `STATZWeb/middleware.py` resolves the namespace and looks it up in `users.AppRegistry`; a mismatch makes permission gating silently no-op. |
| `models/base.py` | App-scoped abstract `AuditModel` (`quote_%(class)s_created` / `_modified`). Redefined locally on purpose — every app declares its own; do not cross-import. |
| `models/rfq.py` | `QuoteRFQ` (`quote_rfq`) — one row per (line, supplier), `unique_together`. Status pipeline `QUEUED` to `READY_TO_SEND` to `SENT` to `RESPONDED`, plus `NO_RESPONSE` / `DECLINED`. Carries `send_attempts` / `last_send_error` for async Graph dispatch diagnostics. |
| `models/quotes.py` | `QuoteSupplierQuote` (`quote_supplier_quote`) — Quote.md's `Supplier_Quotes`. Supplier cost, both adders, packaging source + packhouse FK, markup type/value, `final_government_unit_price`, `is_selected_for_bid` / `selected_automatically`. The `landed_unit_cost` property is Decimal-only. |
| `models/bids.py` | `QuoteBid` (`quote_bid`) — OneToOne on `sales.SolicitationLine`. Every BQ overlay column, plus `clin_group` for Combined-mode CLIN entry and `is_auto_award_solicitation` (char 9 of the sol number is `T`/`U`). |
| `models/email.py` | `QuoteEmail` (`quote_email`) with `raw_payload` + `headers_json` + a 20-minute claim (`CLAIM_DURATION`); `QuoteEmailAttachment` (`quote_email_attachment`, bytes stored); `QuoteEmailSolLink` (`quote_email_sol_link`) — Quote.md's `SOL_Email_Link`, many-to-many email to line. |
| `models/outcomes.py` | `BidOutcome` (`quote_bid_outcome`) — OneToOne on `QuoteBid`, nullable FK to `sales.DibbsAward`, derived `award_unit_price` / `dollar_delta` / `pct_spread` / `within_5_pct`, plus the frozen bid snapshot. |
| `templates/quote/base.html` | App shell. Extends `base_template.html`, defines the `body` block, re-exposes the `content` block. **All quote pages extend this**, never `base_template.html` directly (which has no `content` block). |
| `views/dashboard.py` | Placeholder landing page. Every view carries `@login_required`. |

## 5. Data Model / Domain Objects
All tables use an explicit **`quote_`** `db_table` prefix (`sales` uses `dibbs_`; `suppliers` and
`products` use `contracts_` for legacy alignment). Never let Django auto-name a table.

Money conventions, matching the rest of the repo: unit prices `Decimal(13,5)`, totals
`Decimal(15,2)`, percentages `Decimal(5,2)`, NSN `CharField(max_length=46)`.

- **`QuoteRFQ`** — `unique_together ('line', 'supplier')`; index on `(status, sent_at)`.
- **`QuoteSupplierQuote`** — `rfq` is nullable so a quote can be logged against a line that never
  had an outbound RFQ. Index on `(line, is_selected_for_bid)`.
- **`QuoteBid`** — `line` is a `OneToOneField`, so one bid per line is structural. Split-CLIN is
  therefore the native shape; **Combined mode is the UI aggregation**, recorded by sharing a
  `clin_group` value across sibling lines.
- **`QuoteEmail`** — unlike `sales.InboxMessage`, rows are persisted whether or not a rep has
  linked them, and the full Graph payload is kept. `is_orphan` drives the "No SOL in Subject" pill.
- **`BidOutcome`** — `award_unit_price` is **derived** (`award_total_price / award_quantity`)
  because the DIBBS AW file carries neither quantity nor unit price. `award_unit_price_is_derived`
  defaults `True`; surface it as derived in the UI, never as a figure DIBBS published.

## 6. Request / User Flow
Currently `/quote/` only. The Phase 1 through 4 screens from `quote/docs/Quote.md` are not built yet.

## 7. Templates and UI Surface Area
- `templates/quote/base.html` — shell plus `.quote-subnav`.
- `templates/quote/dashboard.html` — placeholder.
- Styling: **Bootstrap 5.3.3** (Spacelab), already loaded in `base_template.html`'s head.
  New named classes go in `static/css/app-core.css` under the "Quotes app" banner — the repo has a
  three-file CSS architecture and **no new CSS files are permitted**. No Tailwind. No CDN tags in
  quote templates.
- Theme: dark overrides are scoped `[data-bs-theme="dark"] .class`. Never a `.dark` class.
- Drawers use Bootstrap **offcanvas** (`offcanvas-end`); modals use `bootstrap.Modal`; toasts use the
  global `window.showToast(type, message, duration)`.
- The mockups in `quote/docs/` hardcode a dark palette and are layout/IA references only — they are
  not to be pasted in as-is, because the app has a real light/dark toggle.

## 8. Admin / Staff Functionality
`quote/admin.py` registers nothing yet.

## 9. Forms, Validation, Input Handling
None yet. When added: business logic belongs in `quote/services/`, not views.

## 10. Business Logic and Services
`quote/services/` is empty. Planned: a single Decimal-only cost-buildup service (the `sales` app
duplicates its markup formula in five places and mixes `float` into a `Decimal(13,5)` price path —
do not copy that), and a BQ writer.

## 11. Integrations and Cross-App Dependencies

### Read-only dependencies — the core rule of this app
`quote` **reads** and **never writes**:
- `sales.Solicitation`, `sales.SolicitationLine` (including `bq_raw_columns`),
  `sales.ApprovedSource`, `sales.SupplierNSN` / `SupplierFSC` / `SupplierNSNScored`,
  `sales.DibbsAward`, `sales.CompanyCAGE`, `sales.SAMEntityCache`
- `suppliers.Supplier` (including `is_packhouse`, the `packhouse` self-FK, `supplier_type`), `Contact`
- `products.Nsn` — **exception:** the freight sub-modal writes the dimension fields
  (`unit_weight`, `unit_length` / `unit_width` / `unit_height`, `dimension_source_notes`,
  `dimensions_last_verified`). That write is sanctioned; nothing else on `Nsn` is.

### Services worth reusing rather than reimplementing
- `mailer.services.graph_mail.send_mail_via_graph(...)` — outbound. **GCC High only**
  (`graph.microsoft.us`, authority `login.microsoftonline.us`). Returns `False`, never raises.
- `sales.services.graph_inbox` — `fetch_inbox_messages()`, `fetch_message_body(id)`,
  `mark_message_read(id)` against `GRAPH_MAIL_SENDER_RFQ` (`quotes@statzcorp.com` in prod,
  `rfq@statzcorp.com` in dev). On-demand, **not polled**.
- `sales.services.matching.get_live_workbench_matches(line)` and `normalize_nsn(nsn)`.
- `sales.services.competitor_stats.get_competitor_stats()` — **canonical**. `CONTEXT_sales.md`
  says do not duplicate that aggregation.
- `sales.services.bq_export.COMPANY_FILLED_COLUMNS` — the BQ column map.
- Packhouse lookup pattern: `Q(is_packhouse=True) | Q(supplier_type__description__iexact='packhouse')`
  as a sort/highlight hint, **not** a hard filter (precedent `contracts/views/supplier_views.py`).

### Apps that depend on `quote`
None yet.

## 12. URL Surface
| Name | Path | View |
|---|---|---|
| `quote:dashboard` | `/quote/` | `views.dashboard` |

## 13. Permissions / Security Considerations
- Every view must carry `@login_required`. Global behavior varies with `settings.REQUIRE_LOGIN`;
  undecorated views become reachable where login is off.
- **A `users.AppRegistry` row for `quote` has not been created — the app is currently fail-open.**
  `STATZWeb/middleware.py` allows any authenticated user when no `AppRegistry` row exists, and
  denies by default once one does (every non-superuser then needs an explicit
  `AppPermission(has_access=True)`). This is a deliberate open decision; see
  `AGENTS_quote.md` footgun 1.
- Company scoping: `quote` data has **no `company` FK**, matching `sales.Solicitation` and
  `intake.AwardLedger` — DIBBS solicitations are global. Scoping is by CAGE through
  `sales.CompanyCAGE`. Do not invent a company FK.
- `QuoteEmail.body_html` is supplier-supplied HTML. Render it **only** inside a sandboxed
  no-scripts iframe; never inject it into the page DOM.

## 14. Background Processing / Scheduled Work
None registered yet. Adding one needs all three legs or it silently never runs:
1. a zero-arg callable in `quote/tasks/`,
2. an entry in `TASK_FUNCTIONS` in `core/management/commands/run_background_tasks.py` whose key
   exactly matches the `ScheduledTask.name` (case-sensitive),
3. a `core.ScheduledTask` row **seeded by data migration**, not Django admin.

No WebJob redeploy is needed — the 1-minute heartbeat picks up new rows.

Planned: a `quotes@` mailbox poller and a nightly `BidOutcome` reconciliation.

## 14a. Demo Data (dev only)
`python manage.py seed_quote_demo` seeds ten solicitations covering every stage of the workflow:
unmatched, matched-not-dispatched, RFQ queued, RFQ sent, and six bid-submitted records resolving to
2 won / 3 lost / 1 pending — two of the losses inside 5% so the missed-opportunity counter has data.
Also seeds 8 suppliers (one flagged `is_packhouse`), 3 inbound emails (one auto-matched, one covering
two solicitations, one orphan), an attachment, competing quotes on one line for the comparison
drawer, and 121-column BQ templates.

- `--clear` removes it all; `--list` reports what is present.
- **It is a management command, not a data migration, so it never runs on deploy**, and it hard-refuses
  when `settings.IS_PRODUCTION` or `WEBSITE_SITE_NAME` indicates production.
- Every row it creates is tagged so `--clear` can never touch real data: solicitations via an
  `ImportBatch.imported_by='seed_quote_demo'`, awards via a `DEMO-SEED-` `notice_id` prefix,
  suppliers via a marker in `notes`, emails via a `DEMO-SEED-MSG-` `graph_message_id` prefix, and
  NSN rows via a marker in `dimension_source_notes`.
- It **never modifies a pre-existing `contracts_nsn` row** — that is shared product data, so an
  existing NSN is skipped rather than overwritten (and therefore never becomes deletable).

## 15. Testing Coverage
`quote/tests/test_scaffold.py` — app wiring, namespace, explicit `quote_` table prefixes, cross-app FK
targets, Decimal landed-cost math, the auto-award `T`/`U` gate, email claim handoff, the
one-RFQ-per-(line, supplier) constraint, and template render/CDN/Tailwind guards.

`quote/tests/test_permission_seed.py` — the `AppRegistry` / `AppPermission` seeding migration.

`quote/tests/test_seed_quote_demo.py` — the demo seeder: production guard, stage and outcome
coverage, cost-buildup consistency, and the isolation guarantee that `--clear` restores exact
pre-seed row counts and preserves every non-demo row.

Run `python manage.py test quote`.

## 16. Migrations / Schema Notes
- `quote/migrations/0001_initial.py` — creates the seven `quote_*` tables. Additive only.
- `products/migrations/0005_nsn_dimension_source_notes_and_more.py` — adds
  `dimension_source_notes` and `dimensions_last_verified` to `contracts_nsn`.
- No stored procedure writes `contracts_nsn`, and the only migration-created SQLite view
  (`dibbs_we_won_awards`) references `dibbs_award`, so no view drop/recreate guard was needed.
- Any future migration touching a `sales.DibbsAward` field **must** sandwich it between
  `_drop_we_won_awards_view` / `_recreate_we_won_awards_view`.

## 17. Known Gaps / Ambiguities
1. `AppRegistry` registration is undecided (see §13).
2. `Quote.md` pre-flight item 1 says "exactly 99 comma-separated strings" while the same document
   specs a 121-field layout and the live engine writes 121. Treated as **121**; a byte-level diff
   against a DIBBS-accepted `bq` file is the intended proof.
3. A whole-file BQ round-trip ("preserves untouched non-bid lines") is **not possible today** — the
   downloaded `bq` file is deleted after import and only the per-line 121-cell array survives.
   A durable artifact store would be needed.
4. `sales.SolicitationLine` has **no unique constraint on `(solicitation, nsn)`** even though the
   importer keys its diff on that tuple.
5. `item_description_indicator`, `trade_agreements_indicator`, `buy_american_indicator` and
   `higher_level_quality_indicator` on `SolicitationLine` are declared but never populated — the
   values sit in `bq_raw_columns` at columns 105 / 62 / 68 / 117.
6. Quote.md's real-time "another rep is reviewing this row" indicator has **no infrastructure** —
   there are no websockets or Channels in this repo. The in-convention approach is a claim field
   plus a self-scheduling `setTimeout` poll returning a JSON delta.

## 18. Safe Modification Guidance
See `AGENTS_quote.md`.

## 19. Quick Reference
- Tables: `quote_rfq`, `quote_supplier_quote`, `quote_bid`, `quote_email`,
  `quote_email_attachment`, `quote_email_sol_link`, `quote_bid_outcome`
- Namespace: `quote:` — URL prefix: `/quote/` — shell: `quote/templates/quote/base.html`
- Spec and mockups: `quote/docs/`

## 20. CSS Architecture
Three files only, repo-wide: `static/css/theme-vars.css` (brand tokens),
`static/css/app-core.css` (all component/layout classes — **quote classes go here**),
`static/css/utilities.css`. No new CSS files, no Tailwind.
