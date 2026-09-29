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
- Managing the supplier capability lists that feed that matching: view / edit per
  supplier, paste or file import (one supplier or many), export, undo
  (`QuoteCapabilityImport`, `services/capabilities.py`). See §6 "Capabilities".
- Packaging-quote requests emailed to packhouses from the Phase 2 quote drawer, and the
  prices they answer with (`QuotePackhouseRFQ`, `services/packhouse.py`). See §6 Phase 2.
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
| `models/quotes.py` | `QuoteSupplierQuote` (`quote_supplier_quote`) — cost, both adders, packhouse FK, markup, `final_government_unit_price`, `is_selected_for_bid`, `source_email` FK back to the reply it was typed from. `entry` = shared key of the rows one drawer save wrote (a quote as the rep sees it; blank on rows saved before 0010). `landed_unit_cost` is Decimal-only. |
| `models/packhouse.py` | `QuotePackhouseRFQ` (`quote_packhouse_rfq`) — one row per packhouse per request. `SENT → RESPONDED`. `line` null = every line on the SOL (Combined). Snapshot of what was sent (qty, weight / L / W / H, subject, note, recipients) + what came back (`quoted_unit`, `quoted_total`, `quoted_lead_days`, `response_email`). Deliberately **not** `QuoteRFQ`: it never moves the solicitation status. |
| `models/bids.py` | `QuoteBid` (`quote_bid`) — OneToOne on `dibbs.SolicitationLine`; the solicitation is reached via `line.solicitation` (no duplicate FK). Every BQ overlay column + `clin_group`. |
| `models/email.py` | `QuoteEmail` (raw payload, headers, claim), `QuoteEmailAttachment` (bytes), `QuoteEmailSolLink` (many-to-many email ↔ line). |
| `models/outcomes.py` | `BidOutcome` — OneToOne on `QuoteBid`, nullable FK to `dibbs.DibbsAward`, derived deltas, frozen bid snapshot. |
| `services/matching.py` | `seed_solicitation_states`, `match_solicitations`, `process_import_batch`, `add_manual_match` (+ capability learning and sibling re-match), `remove_manual_match`, `rematch_open_solicitations`. Also `preview_matches` (dry run: what would these capability pairs link?) and `prune_derived_matches` (drop NSN/FSC links no capability supports any more). `_index_lines` / `_wanted_matches` are shared by the real run and the dry run, so a preview can never disagree with the commit. |
| `services/capabilities.py` | Everything a rep can do to capability lists: `find_items` (NSN/FSC extraction), `read_text` / `read_upload` (paste, CSV, TXT, XLSX -> `Table`), `SupplierResolver` (CAGE / name / alias -> supplier), `detect_mapping`, `build_plan` (dry run, never writes), `plan_to_preview`, `commit_plan`, `remove_capabilities`, `undo_import`, `capability_overview`, `export_rows`. |
| `services/access.py` | `user_can_use_quote(user)`: mirrors the middleware's `quote` AppPermission rule for pages outside `/quote/` that embed Quotes features (supplier detail / dashboard). |
| `views/capabilities.py` | Capabilities page, per-supplier editor fragment, import page, preview / commit / undo / remove JSON endpoints, CSV export. |
| `static/quote/js/capabilities.js` | One script for the whole feature: importer, editor, drawer, supplier typeahead. Loaded by the Capabilities pages, the solicitation workspace and the supplier detail page. |
| `templates/quote/capabilities/` | `index.html` (page), `import.html` (page), `_editor.html` (fragment: one supplier's lists), `_importer.html` (paste / drop / review widget shared by the editor and the import page). |
| `services/queue.py` | Queue dataset (`build_queue_rows`), `status_counts`, `queue_delta` (poll), `latest_unit_costs`. |
| `services/cost.py` | Decimal landed cost + markup-on-cost pricing (`build`, `price_from_markup`, `markup_from_price`). |
| `services/mailbox.py` | Graph sync + ingest, SOL/NSN detection, supplier resolution, link/unlink, link-modal search. |
| `services/quotes.py` | `save_supplier_quote` (drawer save, creates a new entry), `update_supplier_quote` (rewrites an entry's rows in place; `QuoteLockedError` once its bid went to DIBBS), `saved_cards` / `quotes_for_entry` (what the drawer reopens), `lock_reason` / `bid_state`, lowest-landed auto-select, `save_dimensions` (NSN dimension write-back). |
| `services/packhouse.py` | `parse_dims`, `packaging_requirements` (SolAnalysis, else Section D), `compose_message`, `preview_request` (dry run), `send_requests`, `record_reply`, plus screen data (`requests_payload`, `reply_candidates`, `history`). |
| `services/quote_review.py` | The Quotes page's queries and actions: `waiting_groups`, `logged_cards`, `solicitation_suppliers`, `close_rfqs` / `reopen_rfqs`. |
| `services/drawer.py` | `drawer_payload` (the tray's JSON: lines + NSN dimensions, the supplier's cards, uncovered lines, packhouse data) and `solicitation_group`; shared by the mailbox and the Quotes page. |
| `views/quotes.py`, `views/quote_save.py` | The Quotes page, tray fragment, save, close-out, remove; `quote_save.save_response` turns a tray POST into a save / update (mailbox and Quotes page share it). |
| `static/quote/js/quote-drawer.js`, `quotes-page.js` | The Log quote tray script (`QuoteDrawer.init`, used by both pages) and the Quotes page script. Markup: `templates/quote/mailbox/_tray.html` (include) and `templates/quote/quotes/`. |
| `static/quote/js/attachment-viewer.js` | Split-screen attachment viewer (panel beside the message body, resizable divider, tabs per file, remembers width / open). Served by `views/mailbox.attachment_view`. |
| `views/packhouse.py`, `static/quote/js/packhouse.js` | Preview / send / record-reply endpoints; the drawer's packhouse panel and the message-pane reply banner. |
| `views/mailbox.py` | Phase 2 mailbox + drawer endpoints. |
| `services/bids.py` | Phase 3: bid defaults, `preflight`, `bq_row` / `render_bq` writer, `export_bids`, `reexport`, `reopen_bid`, `select_quote`. |
| `views/bids.py` | Bid Board, compare drawer, builder, export. |
| `services/outcomes.py` + `tasks/reconcile_bid_outcomes.py` | Phase 4: award matching, won/lost + derived deltas, KPI rows, trends. |
| `views/our_bids.py` | Our Bids page, forensic drawer, reconcile-now. |
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
- `QuoteCapabilityImport` (`quote_capability_import`) is the audit record of one
  committed bulk add. `QuoteSupplierNSN.import_batch` / `QuoteSupplierFSC.import_batch`
  (nullable, `SET_NULL`) point at it, which is what makes an import undoable and each
  pairing explainable. Rows added another way (a solicitation's "Save NSN", the demo
  seed) have no batch. Its `created_at` is `default=timezone.now`, not `auto_now_add`.
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

**Capabilities (built) — `/quote/capabilities/`, feeds Phase 1 matching:**
The NSN / FSC lists used to be write-only (a checkbox in a solicitation's Add supplier
modal). They are now first-class, reachable from both directions:
1. **Capabilities page** (`quote:capabilities`, sub-nav "Capabilities" + a dashboard
   tile): suppliers that have a list with NSN / FSC counts, "Still unmatched" KPI,
   export, **Import pairings**, recent imports with **Undo**. Clicking a supplier (or
   "+ Add capabilities for a supplier...") opens the **editor** in a drawer.
2. **Editor** (`capability_supplier`, an HTML fragment): counts + "open solicitations
   linked", FSC chips, the paste / drop importer, and the NSN table (filter, page of
   50, select + remove). The *same fragment* is mounted inline in the supplier detail
   page (`#section-capabilities`, only for users with Quotes access; others see counts)
   and opens in a drawer from each supplier card on a solicitation workspace. Change
   it anywhere and it changed everywhere; the drawer hosts reload their page on close.
3. **Importer**: one widget, two scopes. *One supplier* (fixed by the editor, or picked
   on `/quote/capabilities/import/`): every NSN / FSC found is theirs. *Several
   suppliers*: the file names its supplier per row (CAGE and / or name). Pastes and
   CSV / TXT / XLSX all become a table; `detect_mapping` guesses the header row and each
   column's role from the data (a column of directory CAGEs / names is the supplier, a
   column of NSN/FSC-looking cells is items; header text is only a tie-breaker) and the
   rep can change any column. NSNs are 13 digits in any hyphenation; a bare 4-digit token
   is an FSC; NIINs, 12/14-digit numbers and Excel scientific notation are listed as
   unreadable rather than guessed.
4. **Review before anything is saved** (`capability_import_preview`, `build_plan`):
   new vs already-on-file vs unreadable, per-supplier breakdown with FSC chips showing
   how many open solicitations each class touches, suppliers it could not place (assign
   with the typeahead or skip; unknown / ambiguous / archived), and the **impact**:
   how many open solicitations would gain a supplier link and how many would move
   Unmatched -> Matched (`preview_matches`).
5. **Commit** (`capability_import_commit`) re-reads the same payload (the browser
   re-posts the file), inserts only what is still new (chunked at 200, per-row fallback
   on an `IntegrityError` from a teammate's simultaneous add), records the
   `QuoteCapabilityImport`, then re-matches open solicitations with the new keys
   (`open_matchable_ids` -> `match_solicitations`), exactly like a manual match that
   ticks "Save NSN".
6. **Remove / undo** delete the rows and call `prune_derived_matches`: NSN / FSC links no
   remaining capability supports are dropped, and solicitations left with no supplier go
   back to Unmatched. Only open solicitations still in a matching state are touched;
   worked ones (RFQ sent, quoting...) and MANUAL links are never changed. Undo removes
   exactly the rows that batch created.
7. **Export** (`capability_export`) is a CSV (`Supplier, CAGE, Type, Code, ...`) that the
   importer reads straight back.

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
4a. **Attachments** list with a **View** button on PDFs and images. It opens the file in a panel
   *beside* the message body (`attachment-viewer.js`), not a new tab: drag the divider (or use ←/→ on
   it) to resize, tabs flip between files, ⧉ pops it out to its own tab, ✕ closes. Width and "was
   open" are remembered per browser, so it reappears as you step through messages. Under ~760 px
   it stacks below the message. While the quote drawer is open too, the inbox list steps aside so
   message, attachment and drawer are all on screen. The drawer is **docked, not modal** (no
   backdrop, page stays scrollable, Esc / ✕ still close it).
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

5a. **One drawer, one draft per SOL (and per saved quote).** A message can quote several SOLs, but the
   drawer is a single form, so it keeps a *draft per SOL*, and per saved quote on that SOL (every
   field, Combined / Split + line, which side of packaging / freight was typed, markup mode, typed
   dimensions). Switching SOL stashes the one being left and loads (or blanks) the other, so nothing
   follows the rep from one SOL to the next. Drafts autosave to `localStorage`
   (`quoteDraft:v1:<user>:<email>:<SOL>[|<entry>]`, 14-day expiry) on every edit, so they survive
   closing the drawer, another message, or a reload; a draft is deleted when its quote saves, or
   with **Clear this SOL's entries** / **Undo my changes**. The SOL list marks `• draft` and
   `✓ quote logged` (server: `logged_sols`). The drawer opens where the rep left off (first SOL with
   unsaved work, on its most recently edited quote); else the first SOL with no quote yet; else the
   first SOL's saved quote. Drafts are per browser, not shared.
5b. **Quantity is explicit.** Packaging / freight totals are spread over the quantity being priced
   (all lines in Combined, one line in Split); the drawer says so ("Totals are spread over N units")
   and shows the extended amount (`price × qty`). When that quantity changes (other SOL,
   Combined ⇄ Split, other line) the side of each unit / total pair the rep did **not** type is
   recomputed, so a stale per-unit figure can never sit beside the wrong total.
5c. **One quote per supplier per line, and a logged quote is the thing the tray shows.** A supplier has
   at most one quote on a solicitation line, whichever message or channel it arrived by:
   `save_supplier_quote` **updates** a line the supplier already quoted instead of adding a row (a revised
   quote in a later email, or a phone call, edits the earlier one; the recorded source follows the newest
   touch). Each save is one *entry* (`QuoteSupplierQuote.entry`: the rows it wrote; a line moves to the
   newest save's entry). The tray therefore shows *the sender's quotes on the SOL*, not "this message's":
   opening it on a SOL the supplier already quoted shows that quote, never a blank form. A **Quote**
   picker appears only when there is something to choose (the supplier priced lines separately, or some
   lines are still unquoted): each saved quote ("Line 0001 · $32.50 cost → $43.35 · 45 days") plus
   **＋ Quote the other line(s)**, whose scope is only the lines the supplier has not quoted (the tray
   sends them as `line_ids`, so a new quote can never overwrite a saved one by accident). With a single
   quote covering every line there is no picker; the line under the SOL still says when / by whom / how it
   arrived / where it stands. The **Edit** button beside each row under the message jumps straight to a
   quote. Editing loads exactly what was saved (which side of packaging / freight was typed, markup pill
   or typed price, part, terms, notes), **Update quote** rewrites those rows in place
   (`update_supplier_quote`), and the lines it covers stay fixed (a Combined quote stays all-lines; a
   Split quote stays that line).
   *Pending* = no bid built on the quote has been exported. Then:
   * DRAFT bid on it: price / days follow the edit if the bid still carried the quote's old number
     (a price the rep typed into the bid by hand is kept, and the message says so); margin recomputed.
   * READY bid on it: if price, days or offered part / CAGE changed it goes back to DRAFT ("Needs
     bid") for a re-check and its solicitation drops from `BID_READY` to `QUOTING`.
   * SUBMITTED bid (in a BQ file): the quote is **read-only** ("Sent"): fields disabled, lock note
     with the file name; the server refuses too (409). Reopen the export on the Bid Board to edit.
   `_reselect_lowest` re-picks after an edit and never disturbs a line whose bid was sent. Unsaved
   edits to a saved quote (5a) are kept only while they differ from what is saved, and dropped if the
   quote changed on the server since they began.
5d. **The Quotes page (`/quote/quotes/`, Phase 2 after Mailbox)** is where quotes are chased, reviewed and
   entered when they did not arrive by email (phone, fax, website, a message outside the mailbox).
   * **Waiting on suppliers** (`services/quote_review.waiting_groups`): every `QuoteRFQ` we sent (SENT, or
     RESPONDED with no quote entered) that has no quote from that supplier on that line, one row per
     solicitation + supplier, soonest-due first, on open solicitations only. Shows days waiting, a red /
     amber due badge, and "Replied · not entered" when their message came in but nobody has entered it
     (with **Open reply** to their newest message). **Enter quote** opens the tray; **No response** /
     **Declined…** (with a reason) close the supplier out (`QuoteRFQ` NO_RESPONSE / DECLINED) so they stop
     showing; **Show closed out** lists them with **Back to waiting**. A quote for that supplier (from any
     source) takes them off automatically and marks the RFQ RESPONDED, and a supplier we had written off who
     quotes anyway is back in play.
   * **Logged quotes** (`logged_cards`): every quote on file for open solicitations (toggles: include
     past-due, include ones already sent to DIBBS): SOL, supplier, covers, cost, gov price, days, how it
     arrived ("Phone · Sep 29 · Sam"), bid state with the next step (**Build bid** → the builder,
     **Continue** on a draft, **Export** when ready). There is no "send to Phase 3" trigger: a solicitation
     appears on the Bid Board as soon as it has a quote; the rep's trigger is **Save & mark ready** in the builder. **Edit** opens the same tray on it (**View** and read-only
     once sent); **Remove** deletes a quote nothing rests on (refused while any bid uses it; the supplier
     goes back to waiting on those lines). A supplier with two rows on one line (older data) is flagged
     **Duplicate**.
   * **＋ Enter a quote**: pick a solicitation (same search as the mailbox link picker), then who quoted:
     the suppliers we sent an RFQ to (with Waiting / Has a quote / Closed out) or any other supplier.
   * The tray here is the *same tray* as the mailbox's (`static/quote/js/quote-drawer.js`,
     `templates/quote/mailbox/_tray.html`) with `manual=True`: a **Received via** (phone, fax, email,
     website, other), **Date received** (not in the future) and **Spoke with / reference #** block, saved as
     `source_channel` / `received_on` / `contact_name` with no `source_email`. Saved through
     `POST quotes/<sol>/save/` (channel required), which shares `views/quote_save.save_response` with the
     mailbox save. Editing a quote here keeps its message link unless how / when / who actually changed.
6. **Weight & dimensions** is one block in the drawer, above Packaging and Freight (inputs
   `dim_weight/length/width/height/source_notes`, prefilled from `products.Nsn`). Both
   sections just show a read-out of it (`[data-dims-readout]`, "edit" opens the block), so
   there is one set of figures to keep right, not two mirrored ones. The "save to NSN"
   box applies when a packhouse request is sent or the quote is saved.
7. **Packhouse quotes** (Packaging → "Third-party packhouse" → *Packhouse quotes for this
   SOL*). The rep picks one or more packhouses (typeahead, plus chips for packhouses used on
   this NSN before), adds an optional note, **Preview**s and **Send**s
   (`services/packhouse`). One email per packhouse from the shared mailbox, SOL number in
   subject and body, containing the lines, quantity, the drawer's weight / dimensions, the
   solicitation's packaging requirements (`SolAnalysis`, else `SolPackaging`) and the
   solicitation PDF. Each success writes a `QuotePackhouseRFQ`; a failed send writes
   nothing. A packhouse already asked for the same scope (SENT) is skipped, not re-sent.
   The panel lists every request for the SOL without leaving the drawer.
8. **Their reply** lands in the mailbox like any other. `mailbox.mark_rfqs_responded`
   flips the packhouse request to `RESPONDED` (only if the reply came after it was sent). Opening
   that message shows a **banner** where the rep types the total *or* per-unit price, days and
   notes (`record_reply`; the other price is derived from the quantity asked about). Those
   replies do not count as "Needs quote" in the inbox.
9. Back in the part supplier's drawer, a recorded price gets a **Use** button: it selects the
   packhouse and fills the per-unit packaging price (total follows from the normal
   unit ⇄ total wiring). Saving the quote is unchanged (`packaging_vendor`, `packaging_adder_unit`).

Pricing is **markup on cost**: `price = landed × (1 + pct)`, rounded to cents
(the approved mockup's formula). In Combined mode packaging/freight totals are
spread over the combined quantity of all lines.

**Phase 3 (built) — Bid Board + BQ Export:**
1. `/quote/bids/` Bid Board: open solicitations with ≥ 1 supplier quote, per
   line: tally badge ("3 quotes · Auto: lowest" / "Picked"), selected supplier,
   landed, gov price, days (red when over the SOL's days), bid status. Tabs:
   Needs bid / Ready to export / Submitted (past export files, "Download
   again", "DIBBS rejected it" = reopen to Ready).
2. **Compare** drawer (`compare_quotes`, XHR): every quote per line side by
   side — base, packaging (+ packhouse), freight, landed (+delta vs cheapest),
   gov price, delivery vs required, terms, MOQ, source email. **Select this
   bid** = a rep's pick (`selected_automatically=False`), which auto-select
   never overrides; it also re-points any DRAFT bid.
3. `/quote/bids/<sol>/` builder: one `QuoteBid` per line. Header fields (CAGEs,
   bid type, terms, our quote #, days valid, packaging Y/N, FOB, inspection,
   remarks) apply to every line, as in the BQ file; per-line price, days,
   mfr/dealer, mfr CAGE, FAT waiver, hazmat, material, part offered code /
   CAGE / P/N, quality code. Defaults come from the selected quote, the default
   `CompanyCAGE`, and the line's DIBBS template (`services/bids.default_values`):
   dealer unless the offered CAGE is ours; code 1 (exact) when the offered
   CAGE + P/N is in the AS file, else code 2 with bid type AB. Pre-flight runs
   on every save; **Save & mark ready** only succeeds with zero errors
   (solicitation → `BID_READY`).
4. `/quote/bids/export/`: READY bids with pre-flight; **Download BQ file**
   (`bqYYMMDD-HHMMSS.txt`) is all-or-nothing: bids → `SUBMITTED`,
   `exported_bq_file` set, `BidOutcome` created (`PENDING`) with the frozen
   snapshot, solicitation → `BID_SUBMITTED`.

**BQ writer (`services/bids`).** Starts from each line's DIBBS template
(`bq_raw_columns`), overwrites only STATZ's cells (6, 7, 13, 21–28, 32, 36, 50,
51, 64, 65, 67, 102, 103, 106–108, 118, 120, 121), leaves every other cell as
DIBBS sent it, **never pads**, writes every field quoted, CRLF rows,
ISO-8859-1. Real DIBBS templates arrive pre-filled (24 = BI, 25 = 1, 27 = 90,
29 = NAP, 32/36 = D, 51 = required days...), which is why untouched cells must
survive. Pre-flight errors: template missing / not 121 columns; price ≤ 0,
> 5 dp or too large; days not 1–9999; quoter CAGE not ours; T/U solicitation
with remarks; BI with remarks; BW/AB without remarks; packaging N without
BW/AB; dealer without mfr CAGE; item bought by P/N (col 105 P/B) without P/N +
CAGE; code 1 not in the AS file; code 2 not AB; characters ISO-8859-1 cannot
hold. Warnings: delivery longer than required; template holding U+FFFD.

**Phase 4 (built) — Our Bids (`/quote/our-bids/`):**
1. Reconciliation (`services/outcomes.reconcile`, hourly task
   `reconcile_bid_outcomes` + **Check awards now**) re-checks every outcome
   that is PENDING or rests on a faux award. `find_award`: awards for the SOL
   (FK or indexed `sol_number` -- never `dibbs_solicitation_number`, which is
   unindexed on 900k rows) → same purchase request, else same NSN (excluding
   awards naming a *different* PR), else any award when the SOL has one line;
   priced beats faux, newest first. WON when the awardee CAGE is one of our
   active CAGEs. Award unit price is **derived** = total ÷ our line quantity.
   `within_5_pct` = lost by (0, 5]%.
2. Page: every outcome ships once (json_script); timeframe (Week = 7 days,
   Month = 30 days, Quarter = calendar quarter, All time), status pills
   (All / Won / Lost / Pending / Within 5%) and search filter in the browser and
   recompute the KPI cards: won count + value (our price × qty) + avg markup;
   lost count + value + avg % over winner; win rate over decided bids;
   within-5% count + value.
3. **Details** drawer (`outcome_detail`, XHR): award outcome (PIID linked to
   DIBBS, winner, winning CAGE → entity lookup, total, derived unit, delta),
   frozen bid snapshot, and computed competitive trends
   (`services/outcomes.trends`): our record on the NSN, a what-if at the lowest
   preset markup (or "no markup would have won" when landed ≥ winning), top DLA
   winners on the NSN (2 years), the winner's wins in the FSC, and how bids
   built on this supplier have fared.

Winner names come from our CAGEs, the supplier directory, then cached SAM names
(`entity_names`); reconciliation never calls the SAM API.

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
  `NsnProcurementHistory`, `SolAnalysis` / `SolPackaging` (packaging requirements for
  packhouse requests).
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
- `suppliers` supplier detail page + dashboard embed the capability editor
  (`suppliers.views.capability_context`, lazy imports of `quote.services.access` /
  `quote.models`). Capabilities stay Quotes data: editing needs Quotes access even from
  a supplier page.
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
| `quote:capabilities` | `/quote/capabilities/[?supplier=<id>]` | page; `?supplier=` opens that supplier's drawer |
| `quote:capability_supplier` | `/quote/capabilities/supplier/<id>/?q=&page=` | editor fragment (XHR only; a direct visit redirects to the page with the drawer open) |
| `quote:capability_remove` | `/quote/capabilities/supplier/<id>/remove/` | POST JSON `{nsns, fscs}` |
| `quote:capability_import` | `/quote/capabilities/import/[?supplier=<id>]` | import page |
| `quote:capability_import_preview` / `capability_import_commit` | `/quote/capabilities/import/preview/` / `commit/` | POST multipart: `file` or `text`, `supplier_id`, `mapping`, `assignments` → JSON |
| `quote:capability_import_undo` | `/quote/capabilities/import/<id>/undo/` | POST, JSON (409 when already undone) |
| `quote:capability_export` | `/quote/capabilities/export/[?supplier=<id>]` | CSV, streamed |
| `quote:rfq_queue` / `rfq_send` / `rfq_send_all` / `rfq_remove` | `/quote/rfq/...` | POST except the queue page |
| `quote:mailbox` | `/quote/mailbox/?email=<id>` | inbox page |
| `quote:mailbox_sync` | `/quote/mailbox/sync/` | POST, JSON |
| `quote:email_detail` | `/quote/mailbox/<id>/` | XHR fragment (non-XHR redirects to the inbox) |
| `quote:email_link` / `email_unlink` / `email_set_supplier` / `save_quote` | `/quote/mailbox/<id>/...` | POST, JSON. `save_quote` with `entry=<key>` updates that logged quote (404 if it is not this message's, 409 `{locked: true}` once sent to DIBBS); without `entry` it creates one |
| `quote:mailbox_sol_search` | `/quote/mailbox/solicitations/?q=` | JSON |
| `quote:bid_board` | `/quote/bids/?tab=needs\|ready\|submitted` | |
| `quote:compare_quotes` | `/quote/bids/<sol>/compare/` | XHR fragment |
| `quote:select_quote` | `/quote/quotes/<id>/select/` | POST, JSON |
| `quote:bid_builder` | `/quote/bids/<sol>/` | GET / POST (`action=draft\|ready`) |
| `quote:bid_export` | `/quote/bids/export/` | GET list, POST `bid_ids` → file |
| `quote:bid_reexport` / `bid_reopen_export` | `/quote/bids/export/<file>/` (`reopen/`) | GET file / POST |
| `quote:our_bids` | `/quote/our-bids/` | |
| `quote:outcome_detail` | `/quote/our-bids/<id>/` | XHR fragment |
| `quote:reconcile_now` | `/quote/our-bids/reconcile/` | POST |
| `quote:quotes` | `/quote/quotes/?tab=waiting\|logged&closed=1&sent=1&past=1` | the Quotes page |
| `quote:quote_tray` | `/quote/quotes/tray/?sol=&supplier=` | tray fragment for a chosen SOL + supplier (XHR) |
| `quote:quote_save` | `/quote/quotes/<sol>/save/` | POST: the tray's fields + `supplier_id`, `source_channel` (required), `received_on`, `contact_name`, optional `entry` / `line_ids` |
| `quote:quote_sol_suppliers` | `/quote/quotes/sol-suppliers/?sol=` | JSON: who we sent an RFQ to on that SOL |
| `quote:rfq_close` | `/quote/quotes/rfq-close/` | POST `sol`, `supplier_id`, `action=no_response\|declined\|reopen`, `reason` |
| `quote:quote_remove` | `/quote/quotes/remove/` | POST `sol`, `supplier_id`, `entry`; 404 unknown, 400 bid rests on it, 409 sent to DIBBS |
| `quote:packhouse_preview` / `packhouse_send` | `/quote/packhouse/<sol>/preview/` / `send/` | POST: `packhouse_ids` (repeat), `line_id` (Split only), `note`, `dim_*`, `save_dims` → JSON |
| `quote:packhouse_record_reply` | `/quote/packhouse/reply/<rfq_id>/` | POST: `total` or `unit`, `lead_days`, `notes`, `email_id` → JSON |
| `quote:attachment_view` | `/quote/mailbox/attachments/<id>/view/` | inline PDF / PNG / JPEG / GIF / WebP for the viewer; type from the bytes, else 415; `X-Frame-Options: SAMEORIGIN` (site default is DENY) |
| `quote:attachment_download` | `/quote/mailbox/attachments/<id>/` | always `octet-stream` + `nosniff`, except verified PDFs inline |

## 13. Permissions / Security
- `@login_required` on every view.
- `AppRegistry`: `quote/0002` created a `quote` row (deny-by-default) and granted it
  to users who had `sales` access. **Non-superusers need an explicit
  `AppPermission(has_access=True)`** — there is no auto-grant signal.
- No `company` FK on quote data; scope by CAGE via `dibbs.CompanyCAGE`.
- `QuoteEmail.body_html` is supplier HTML: render only in a sandboxed no-scripts iframe.
- Capability endpoints are `quote:` URLs, so they are gated like everything else here.
  The supplier detail page checks `user_can_use_quote` up front so it only offers the
  editor to people who can reach it. Uploads are capped at 10 MB / 100,000 rows;
  `.xls` is refused; the CSV export neutralises formula-looking cells.

## 14. Background Work
- `import_completed` receiver (synchronous, inside the import request / WebJob).
- `archive_stale_solicitations` (daily, run_order 9) — `quote/tasks/`, seeded by `0005`.
- `reconcile_bid_outcomes` (hourly, run_order 10) — seeded by `0007`.
- Mailbox sync is on demand (**Check for new mail**); no poller.

## 14a. Demo Data (dev only)
`python manage.py seed_quote_demo` seeds ten solicitations across every stage
(unmatched, matched, RFQ queued/sent, six bid-submitted → 2 won / 3 lost /
1 pending, two losses within 5%), with `QuoteSolicitation` state, capabilities
and matches. `--clear` / `--list`. Refuses to run in production. Every row is
tagged (import batch `imported_by`, `DEMO-SEED-` notice/message ids, supplier
notes marker, NSN `dimension_source_notes` marker) and it never modifies a
pre-existing `contracts_nsn` row.

## 15. Testing
`test_quote_manual.py` (one quote per supplier per line: re-quoting updates, from a later message or a phone
call, other suppliers untouched, refused once sent; manual entry channel / date rules and RFQ effects; edit
follows the newest source; delete; `waiting_groups`, `logged_cards`, close-out / reopen),
`test_quotes_page.py` (the page, nav link, tray fragment, save / update / lock, `line_ids`, close-out,
remove, enter-a-quote picker, login required),
`test_quote_edit.py` (entries + saved-card shape incl. typed sides / FIXED price / legacy key-less
rows, in-place update over the quote's own lines, rejected edits change nothing, the lock, bid follow /
demote rules, re-pick, `save_quote` update path 404 / 409 / 400, Edit buttons, no template syntax
leaking to the page),
`test_mailbox_drawer.py` (attachment sniffing + `attachment_view` rules, View buttons, multi-SOL
`logged` markers, draft owner, docked drawer markup),
`test_packhouse.py` (dimension parsing, requirements lookup, message, preview never sends,
send / duplicate / failure / no-address, NSN write-back, record reply maths, mailbox reply hook,
endpoints, banner + shared dimensions block),
`test_scaffold.py` (wiring, table prefixes, FK targets, landed cost, auto-award
gate, claims, RFQ uniqueness, templates), `test_phase4.py` (pending → won / lost, derived unit + deltas, within 5%, faux
→ real upgrade, purchase-request line matching, trends what-if, task, views),
`test_phase3.py` (bid defaults, every pre-flight rule, writer preserves the
DIBBS template / never pads / QUOTE_ALL + CRLF + 121 columns, export → snapshot
→ re-download → reopen, all-or-nothing export, manual pick sticks, views),
`test_phase2.py` (cost math, SOL/NSN detection, ingest + supplier resolution,
Graph sync (mocked — tests must never call Graph), drawer save combined/split,
auto-select, NSN dimensions, sandboxed body + CSP, attachment headers),
`test_capabilities.py` (NSN/FSC extraction, paste / CSV / XLSX reading, supplier
resolution, column detection, dry-run plan + impact, commit / remove / undo and their
effect on matching, every capability endpoint, supplier-page / workspace / dashboard
integration, `user_can_use_quote`),
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
- `0007_seed_reconcile_task` — `ScheduledTask` row for `reconcile_bid_outcomes`.
- `0008_capability_imports` — `QuoteCapabilityImport` + nullable `import_batch` FK on
  `QuoteSupplierNSN` / `QuoteSupplierFSC`. Additive only.
- `0009_packhouse_rfq` — `QuotePackhouseRFQ`. Additive only.
- `0010_supplier_quote_entry` — `QuoteSupplierQuote.entry` (blank default, indexed). Additive only; no
  backfill: older key-less rows are grouped at read time and pinned with a real key on their first edit.
- `0011_quote_source_channel` — `QuoteSupplierQuote.source_channel` (default EMAIL), `received_on`,
  `contact_name`. Additive only; existing rows read as email quotes with no date.
- `products/migrations/0005` added the NSN dimension provenance fields.

## 17. Known Gaps
1. The BQ writer's quoting (every field quoted) and CRLF line endings follow
   Quote.md but are **unproven against DIBBS**. Before the first live upload,
   diff an export against a DIBBS-accepted `bq` file (or upload one test bid).
2. Whole-file BQ round-trip is impossible today — the downloaded file isn't kept.
3. Real-time "another rep is reviewing" needs no websockets: claim fields +
   self-scheduling `setTimeout` poll.
4. Margin presets are **markup on cost** (settled by the Option B mockup's formula).
5. The "Supplier always requires external packaging" toggle has no quote-owned home yet.
6. Backfilled rows all carry the migration time as `status_changed_at`, so every
   currently-unmatched solicitation archives on the same day, 7 days after `0004` ran.
7. Approved sources are not an automatic match source (spec lists NSN / FSC /
   Manual only); the workspace offers one-click **Link** instead.
8. Capability import is add-only: there is no "replace this supplier's list with this
   file". Bare 4-digit numbers in an items column are read as FSCs, so a quantity column
   read as items shows up as odd FSCs in the review (each shows how many open SOLs it
   touches). NIIN-only lists cannot be resolved to an NSN (no indexed NIIN column) and
   are reported as unreadable.
9. Capability inserts use `bulk_create` at 200 rows, as `match_solicitations` already does.
   The `AGENTS_quote.md` note about `auto_now_add` and SQL Server error 8115 predates
   this; the feature has only been exercised on SQLite. Smoke-test a ~1,000-pair paste on
   the SQL Server dev database after deploying.
10. Matching only runs on import, manual link and capability changes. Capabilities written
   any other way (admin, a script, the demo seed) don't link existing solicitations until
   **Re-run matching** on the queue.

11. Packhouse requests are one-shot: no follow-up / re-send while one is SENT for the same scope,
   no "declined" state (a reply that names no price just stays `RESPONDED` with no price), and
   no way to start one except the quote drawer (which needs a mailbox message with a linked SOL
   and a known supplier). The reply is matched by sender → supplier, so a reply from an address
   we don't know as that packhouse won't flip its request until the rep sets the supplier.
12. One set of weight / dimensions serves packaging and freight, but they are really two
   measurements: the packhouse needs the bare part, freight needs the packed carton.
   `products.Nsn` only stores the part. A "packed" set would need new Nsn fields (a sanctioned
   cross-app change) — not built.
13. Combined mode with several *different* NSNs on one SOL shares one set of dimensions
   (preview warns; the pre-existing NSN write-back also writes them to every NSN). Ask per line
   with Split CLINs when the parts differ.
14. Not yet exercised on SQL Server: the reply hook's `update()` filters through
   `solicitation__lines__quote_email_links` (same shape as the `QuoteRFQ` one). Smoke-test after
   deploying.

15. Drawer drafts live in the browser (`localStorage`): another rep, another machine or a cleared
   browser does not see them. Server-side drafts would need a model and a claim rule.
16. The viewer previews only what the browser can show itself (PDF via its built-in viewer, raster
   images). Word / Excel / CSV attachments still download. The PDF frame deliberately has no
   `sandbox` attribute (browsers refuse to run their PDF viewer in a sandboxed frame); safety comes
   from serving only bytes that sniff as PDF / raster image, `nosniff`, and a no-load CSP.
17. The drawer's Min order qty is recorded but does not change the price. A supplier MOQ above the
   SOL quantity (or a price break) is still for the rep to fold into the unit cost by hand.
18. The tray form is one hand-written script, `static/quote/js/quote-drawer.js` (shared by the mailbox and
   the Quotes page). A new tray field must be added to `TEXT_FIELDS` (or `snapshot()` / `applyDraft()` /
   `resetForm()` / `applyCard()`) or it will leak between SOLs again.
19. An edit cannot change which lines a quote covers (a Combined quote stays all-lines, a Split quote
   stays that line). To restructure, **Remove** the quote on the Quotes page and enter it again. Remove is
   refused while any bid rests on the quote.
20. "One quote per supplier per line" is enforced by the service (`save_supplier_quote` updates in place),
   not by a database constraint, because older data can hold duplicates and a constraint would fail the
   migration. Such rows are flagged **Duplicate** on the Quotes page; a save updates the newest and
   **Remove** clears the rest. Older rows saved before `entry` existed are grouped by SOL + identical
   numbers; rows written by the demo seed or scripts have no key until first edited.
21. The waiting list is built from `QuoteRFQ` rows, so a supplier we never RFQ'd through the app (asked by
   phone, say) is not on it; use **Enter a quote** for those. **Enter quote** on a waiting row opens the
   tray with every line open, not just the lines that RFQ covered: pick Split to enter one line.
22. Manual entry stores how / when / who but not the fax or PDF itself. Attaching the document to the quote
   (and viewing it beside the tray) would need file storage on the quote.
23. Removing the only quote on a SOL leaves the solicitation in QUOTING (it does not step back to RFQ sent).
24. The bid follows an edit only for price, days, margin and status. Other bid fields derived from the
   quote when the bid was created (offered code, manufacturer / dealer, vendor quote #) are not
   re-derived; a changed part number / CAGE is flagged in the save message instead.

## 20. CSS
Three files repo-wide: `theme-vars.css`, `app-core.css` (shared `.app-shell` /
`.app-subnav` live under the "App shell + sub-nav" banner), `utilities.css`.
