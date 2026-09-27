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
| `services/matching.py` | `seed_solicitation_states`, `match_solicitations`, `process_import_batch`, `add_manual_match` (+ capability learning and sibling re-match), `remove_manual_match`, `rematch_open_solicitations`. |
| `services/queue.py` | Queue dataset (`build_queue_rows`), `status_counts`, `queue_delta` (poll), `latest_unit_costs`. |
| `services/cost.py` | Decimal landed cost + markup-on-cost pricing (`build`, `price_from_markup`, `markup_from_price`). |
| `services/mailbox.py` | Graph sync + ingest, SOL/NSN detection, supplier resolution, link/unlink, link-modal search. |
| `services/quotes.py` | `save_supplier_quote` (drawer save), lowest-landed auto-select, NSN dimension write-back. |
| `views/mailbox.py` | Phase 2 mailbox + drawer endpoints. |
| `services/walk.py` | `claim_next` — next-available navigation for work-the-list mode. |
| `services/rfq.py` | `queue_rfqs`, `resolve_recipients`, `compose_message`, `pending_groups`, `send_supplier_rfqs`. |
| `services/archival.py` + `tasks/archive_stale_solicitations.py` | 7-day / past-due archival (daily `ScheduledTask`, seeded by `0005`). |
| `views/solicitations.py`, `views/rfq.py` | Phase 1 screens (orchestration only). |
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
**Phase 1 (built):**
1. Every DIBBS import seeds `QuoteSolicitation` rows and runs NSN/FSC matching.
2. `/quote/solicitations/` — queue of open solicitations (return-by ≥ today) in
   Unmatched / Matched / RFQ Sent tabs. The whole open set loads once from
   `queue_data` (columnar, gzipped, ~3 s for ~11k rows) and filters client-side:
   set-aside, due-date and estimated-value pills + text search. Est. value =
   qty × latest DLA unit price (`NsnProcurementHistory`). A self-scheduling
   30 s poll (`queue_poll`) applies status moves and shows who is reviewing a row.
3. `/quote/solicitations/<sol>/` — workspace. Opening it takes the 20-minute
   review claim (banner + "Take over" if someone else holds it). Shows lines,
   approved sources (one-click **Link** when the CAGE is in the supplier
   directory), recent DLA purchases, linked suppliers with NSN/FSC/Manual badges.
   **Add supplier** modal: search by name/CAGE/type, optional "save NSN / FSC to
   this supplier" — saved capabilities immediately re-match other open
   solicitations. Tick suppliers → **Queue RFQ**. **No bid** / **Reopen**.
3a. **Work the list.** Clicking a SOL (or **Start working this list**) snapshots the
   current filtered, sorted list into `sessionStorage['quoteRun']`; the queue is
   not reloaded while working. The workspace shows a sticky run bar (position,
   progress, Prev / Next / Exit, keys `N` / `P`) and swaps in **No bid & next** /
   **Queue RFQ & next** (fetch POSTs that answer JSON, then advance).
   Next = `POST /quote/solicitations/next/` with the upcoming candidates:
   `services/walk.claim_next` skips SOLs held by a teammate, no longer in the
   list's status, or past due, and claims the first free one with
   `QuoteSolicitation.try_claim` — one conditional UPDATE, so two reps can never
   land on the same SOL. Skips surface as a toast on the next page. The open
   workspace renews its claim every 5 min (`claim` action `renew`) and warns if
   a teammate took over. A rep holds at most one claim at a time.
4. `/quote/rfq/` — RFQ Queue: one card per supplier with recipients, preview,
   Send / Send all. One consolidated email per supplier (SOL # in subject and
   body, stored PDFs attached up to ~2.8 MB, DIBBS link always in the body).
   Success → RFQs `SENT`, solicitations `RFQ_SENT`. Failure changes nothing but
   `send_attempts` / `last_send_error`.
5. Daily `archive_stale_solicitations` task: Unmatched > 7 days and any
   Unmatched/Matched past due → `ARCHIVED`.

Recipients: Sales-category contacts, else `rfq_email`, else `business_email`,
else `primary_email` (`services/rfq.resolve_recipients`).

**Phase 2 (built) — `/quote/mailbox/`, Option B:**
1. **Check for new mail** (`mailbox_sync`) pulls the newest 50 inbox messages via
   Graph and stores unseen ones: full body, headers, raw payload, file
   attachments (≤ 15 MB stored; larger keep metadata only).
2. Detection (`services/mailbox.auto_link`): SOL numbers in subject/body link
   every line of that SOL; failing that, NSNs link only lines we sent an RFQ
   for. Sender → supplier via contact email, supplier emails, then domain
   (public mail domains ignored). A reply from an RFQ'd supplier flips its
   RFQs to `RESPONDED`. Unlinked mail is an orphan ("No SOL").
3. Inbox (left) filters client-side: All / No SOL / Needs quote / Unread +
   search; ↑/↓ move between messages. Selecting one swaps in a detail fragment
   (`email_detail`, XHR) — no page reload — and takes the email's 20-minute claim.
   Read state is app-only: the real mailbox is never marked read (reps watch
   its unread count in Outlook). The sync is read-only against Graph.
4. Message pane: supplier (or **Set supplier**), linked SOL chips (unlink ×,
   **+ Link SOL** search by SOL/NSN/part #), attachments, body, quotes already
   logged from it. Body renders only in `<iframe sandbox="allow-popups
   allow-popups-to-escape-sandbox" srcdoc>` with a CSP meta blocking scripts and
   every remote load (tracking pixels, external CSS).
5. **Log supplier quote** opens the offcanvas drawer: solicitation, Combined
   (all lines) / Split CLINs, facts, part/CAGE, unit cost, days ARO (SOL
   requirement shown), MOQ, terms, packaging (who packages, packhouse search,
   unit ⇄ total), freight (unit ⇄ total, NSN dimensions pre-filled with
   "save/update dimensions"), tip-screen markup 2/4/6/Custom or type a final
   price to back-calculate. The browser previews; `services/cost.build` is the
   authority. Save (`services/quotes.save_supplier_quote`) creates one
   `QuoteSupplierQuote` per line, links the email, flips the RFQ to
   `RESPONDED`, moves the SOL to `QUOTING`, and auto-selects the lowest landed
   quote per line unless a rep already chose one.

Pricing is **markup on cost**: `price = landed × (1 + pct)`, rounded to cents
(the approved mockup's formula). In Combined mode packaging/freight totals are
spread over the combined quantity of all lines.

Phases 3–4 (bid staging + BQ export, Our Bids) are not built.

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
| Name | Path | Notes |
|---|---|---|
| `quote:dashboard` | `/quote/` | pipeline counts |
| `quote:solicitation_queue` | `/quote/solicitations/` | `?tab=UNMATCHED\|MATCHED\|RFQ_SENT` |
| `quote:queue_data` | `/quote/solicitations/data/` | JSON, gzipped |
| `quote:queue_poll` | `/quote/solicitations/poll/?since=` | JSON delta |
| `quote:rerun_matching` | `/quote/solicitations/rematch/` | POST |
| `quote:walk_next` | `/quote/solicitations/next/` | POST JSON `{candidates, status, release}` |
| `quote:solicitation_workspace` | `/quote/solicitations/<sol>/` | takes the claim |
| `quote:add_match` / `remove_match` / `queue_supplier_rfqs` / `set_status` / `claim` | `/quote/solicitations/<sol>/...` | POST |
| `quote:supplier_search` | `/quote/suppliers/search/?q=` | JSON |
| `quote:rfq_queue` / `rfq_send` / `rfq_send_all` / `rfq_remove` | `/quote/rfq/...` | POST except the queue page |
| `quote:mailbox` | `/quote/mailbox/?email=<id>` | inbox page |
| `quote:mailbox_sync` | `/quote/mailbox/sync/` | POST, JSON |
| `quote:email_detail` | `/quote/mailbox/<id>/` | XHR fragment (non-XHR redirects to the inbox) |
| `quote:email_link` / `email_unlink` / `email_set_supplier` / `save_quote` | `/quote/mailbox/<id>/...` | POST, JSON |
| `quote:mailbox_sol_search` | `/quote/mailbox/solicitations/?q=` | JSON |
| `quote:attachment_download` | `/quote/mailbox/attachments/<id>/` | always `octet-stream` + `nosniff`, except verified PDFs inline |

## 13. Permissions / Security
- `@login_required` on every view.
- `AppRegistry`: `quote/0002` created a `quote` row (deny-by-default) and granted it
  to users who had `sales` access. **Non-superusers need an explicit
  `AppPermission(has_access=True)`** — there is no auto-grant signal.
- No `company` FK on quote data; scope by CAGE via `dibbs.CompanyCAGE`.
- `QuoteEmail.body_html` is supplier HTML: render only in a sandboxed no-scripts iframe.

## 14. Background Work
- `import_completed` receiver (synchronous, inside the import request / WebJob).
- `archive_stale_solicitations` (daily, run_order 9) — `quote/tasks/`, seeded by `0005`.
- Planned: `quotes@` mailbox poller, nightly `BidOutcome` reconciliation.

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
gate, claims, RFQ uniqueness, templates), `test_phase2.py` (cost math, SOL/NSN detection, ingest + supplier resolution,
Graph sync (mocked — tests must never call Graph), drawer save combined/split,
auto-select, NSN dimensions, sandboxed body + CSP, attachment headers),
`test_phase1.py` (queue dataset/estimate, claims + poll, manual match learning,
RFQ queue/compose/send success + failure, recipients, archival), `test_matching.py` (import signal →
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
- `0005_seed_archive_task` — `ScheduledTask` row for `archive_stale_solicitations`.
- `0006_email_supplier` — nullable `QuoteEmail.supplier` FK (resolved sender).
- `products/migrations/0005` added the NSN dimension provenance fields.

## 17. Known Gaps
1. `Quote.md` pre-flight item 1: treat BQ rows as **121** columns; prove with a
   byte-level diff against a DIBBS-accepted `bq` file.
2. Whole-file BQ round-trip is impossible today — the downloaded file isn't kept.
3. Real-time "another rep is reviewing" needs no websockets: claim fields +
   self-scheduling `setTimeout` poll.
4. Margin presets are **markup on cost** (settled by the Option B mockup's formula).
5. The "Supplier always requires external packaging" toggle has no quote-owned home yet.
6. Backfilled rows all carry the migration time as `status_changed_at`, so every
   currently-unmatched solicitation archives on the same day, 7 days after `0004` ran.
7. Approved sources are not an automatic match source (spec lists NSN / FSC /
   Manual only); the workspace offers one-click **Link** instead.

## 20. CSS
Three files repo-wide: `theme-vars.css`, `app-core.css` (shared `.app-shell` /
`.app-subnav` live under the "App shell + sub-nav" banner), `utilities.css`.
