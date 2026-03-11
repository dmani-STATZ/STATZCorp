## Summary — DIBBS Sales app build-out
1. sales/services/importer.py
run_import(in_file, bq_file, as_file, imported_by)
Parses IN/BQ/AS via parse_import_batch() from sales.services.parser.
Derives import_date from IN filename (e.g. IN260308.TXT → 2026-03-08).
Wraps all DB work in transaction.atomic().
Solicitations: get_or_create by solicitation_number; updates return_by_date, status, set_aside, etc. on re-import.
SolicitationLine: get_or_create by (solicitation, nsn); fills from IN and BQ (line_number, delivery_days).
Calls assign_triage_bucket(ps) per parsed line (logged; no DB field).
ApprovedSource: deletes existing AS for the same import_date, then bulk creates AS for the new batch.
Returns a summary dict (counts, parse errors, solicitations_with_errors).
2. sales/forms.py
ImportUploadForm with three file fields: in_file, bq_file, as_file.
3. sales/views/imports.py
import_upload(request): GET shows upload form; POST validates, runs run_import(), then renders the same template with a green summary card or form errors. @login_required applied.
4. sales/views/solicitations.py
solicitation_list(request):
List ordered by return_by_date (asc).
Optional GET filters: set_aside, item_type, status, q (sol# or nomenclature).
Context: solicitations (paginated, 50/page), set_aside_choices, status_choices, current_filters.
Uses prefetch with annotated match_count per line and exposes total_match_count and first_line per solicitation.
5. sales/urls.py and project URLs
sales/urls.py:
'' → dashboard
'import/' → import_upload
'solicitations/' → solicitation_list
Project already has path("sales/", include("sales.urls")); app_name = 'sales' provides the sales: namespace.
6. Templates
sales/templates/sales/base.html: Extends base_template.html, adds a left sidebar with Dashboard, Solicitations, Import (with active state).
sales/templates/sales/import/upload.html: Three file inputs; on success shows green summary card and optional yellow parse-error card; simple form (no drag-and-drop).
sales/templates/sales/solicitations/list.html: Filter bar (Set-Aside, Status, Item type, search); table with Sol#, NSN, Nomenclature, Qty, Unit, Set-Aside, Return By, Status, Match count; SDVOSB (set_aside = R) rows highlighted; pagination; sol# links to # for future detail.
Notes
Parser: Importer uses sales.services.parser (parse_import_batch, assign_triage_bucket). No changes were made to the parser.
Dashboard: Implemented as a stub that redirects to solicitation list.
Set-aside codes: R = SDVOSB (priority), N/Y/H/L/A/E as in your spec; list view uses these for filter and display.
Output checklist


sales/services/importer.py

sales/forms.py

sales/views/__init__.py

sales/views/imports.py

sales/views/solicitations.py

sales/urls.py

Project
urls.py
(already included; namespace via
app_name
)

sales/templates/sales/base.html

sales/templates/sales/import/upload.html

sales/templates/sales/solicitations/list.html
manage.py check passes and the sales URLs resolve to /sales/, /sales/import/, and /sales/solicitations/. You can run the dev server and test the import flow and solicitation list with filters.


## Summary of what was implemented:

1. sales/services/matching.py
_normalize_nsn(nsn) – strips hyphens and whitespace.
_match_tier1_nsn(line) – exact NSN match on dibbs_supplier_nsn, ordered by match_score desc, excludes archived suppliers; returns dicts with supplier_id, match_tier=1, match_method='DIRECT_NSN', match_score from SupplierNSN.
_match_tier2_approved_source(line) – gets approved CAGEs from ApprovedSource for the normalized NSN, then looks up Supplier by cage_code (from suppliers.models), match_score=1.0, match_method='APPROVED_SOURCE'.
_match_tier3_fsc(line) – matches on line.fsc via SupplierFSC, match_score=0.5, match_method='FSC'.
_deduplicate_matches(tier1, tier2, tier3) – keeps one match per supplier (lowest tier number wins).
run_matching_for_batch(batch_id) – loads all lines for the batch, deletes existing SupplierMatch for those lines, skips lines with item_type_indicator == '2' for Tiers 1 and 2 (Tier 3 still runs), runs all three tiers, deduplicates, bulk creates SupplierMatch with is_excluded=False. Returns {lines_processed, matches_found, by_tier: {1, 2, 3}}.
backfill_nsn_from_contracts(dry_run=False) – uses contracts.models.Clin (the actual model name). Excludes packhouse suppliers, groups by (normalized_nsn, supplier_id), applies recency weights (≤2y=1.0, ≤5y=0.6, ≤10y=0.3, else 0.1), update_or_create on (nsn, supplier_id) with source='contract_history', skips when source='manual', runs in transaction.atomic() when not dry run. Returns {processed, created, updated, skipped_manual, errors}.
2. Import flow and upload template
sales/services/importer.py – After the main transaction.atomic() block, calls run_matching_for_batch(batch.id) and adds match_summary to the returned result. Final counts (created_sol, updated_sol) are computed before building the result.
sales/templates/sales/import/upload.html – Success card now includes:
Matches found: X (Tier 1: X Tier 2: X Tier 3: X).
sales/views/imports.py – Passes match_tier_1, match_tier_2, match_tier_3 in the context so the template can show tier counts without using integer dict keys.
3. Backfill view, URL, and template
sales/views/suppliers.py – New backfill_nsn view: GET shows confirmation; POST runs the backfill. Dry run when dry_run=1 (GET or POST). Protected with @login_required and @user_passes_test(_staff_required) (staff only).
sales/urls.py – Added path('suppliers/backfill-nsn/', backfill_nsn, name='backfill_nsn').
sales/templates/sales/suppliers/backfill_nsn.html – Warning text, “Dry Run” and “Run Backfill” buttons, and a results card (processed, created, updated, skipped_manual, errors).
4. Notes
Contract / CLIN – Backfill uses Clin from contracts.models and reads award_date from clin.contract.award_date; NSN comes from clin.nsn.nsn_code (products.Nsn).
Tier 2 – ApprovedSource is stored with nsn_raw (no hyphens) in the importer, so querying with _normalize_nsn(line.nsn) is correct.
Supplier flags – Archived suppliers are excluded in all tiers. is_excluded is set to False for all matches; probation/conditional are left for the UI to display.
python manage.py check passes. You can run a real import to confirm matching and open /sales/suppliers/backfill-nsn/ (as a staff user) to run or dry-run the backfill.


## Summary — Session 3 implementation
1. Importer: write bucket to Solicitation (sales/services/importer.py)
In get_or_create defaults: added "bucket": assign_triage_bucket(ps) and "bucket_assigned_by": "auto".
In the update branch: if solicitation.bucket == "UNSET", set bucket and bucket_assigned_by and added both to update_fields.
2. Solicitation model (sales/models/solicitations.py)
Added bucket, bucket_assigned_by, and BUCKET_CHOICES / BUCKET_ASSIGNED_BY_CHOICES.
Extended STATUS_CHOICES with pipeline statuses (Matching, RFQ_PENDING, RFQ_SENT, QUOTING, BID_READY, BID_SUBMITTED, NO_BID, etc.).
Added days_remaining property (from return_by_date vs today).
Migration: 0003_add_solicitation_bucket.py (applied).
3. Views (sales/views/solicitations.py)
_build_pipeline_steps(current_status) — builds the 7-step pipeline list for the detail page.
solicitation_detail(request, sol_number) — detail with Overview and Matches tabs; pipeline track; header card; approved sources; matches table; RFQs/Quotes/Bid stubbed.
no_bid(request, sol_number) — POST-only; sets status to NO_BID, message, redirect to detail.
global_search(request) — ?q=...&fmt=json returns up to 8 results for typeahead; without fmt=json renders full search results page (up to 50).
solicitation_list — bucket filter (default exclude SKIP), bucket_counts and filter_querystring in context; pagination uses filter_querystring.
4. Dashboard (sales/views/dashboard.py)
Real dashboard with: today, latest_batch, counts_by_status, counts_by_bucket, urgent_count (≤3 days, active only), total_active, recent_solicitations (10, non-Skip, with first_line).
5. URLs (sales/urls.py)
solicitations/<str:sol_number>/ → solicitation_detail
solicitations/<str:sol_number>/nobid/ → no_bid
dashboard/ → dashboard (root '' already pointed to dashboard)
search/ → global_search
6. Templates
sales/solicitations/detail.html — Pipeline track, header card (metadata + quick actions: Send RFQs / Build Bid / Mark No-Bid), tab bar (Overview, Matches, RFQs, Quotes, Bid), Overview (bucket, import info, approved sources table), Matches (table with tier badges, supplier link, Send RFQ placeholder), RFQs/Quotes/Bid stubs.
sales/dashboard.html — Topbar + last import chip, urgent alert, 5 stat cards, 4 bucket mini-cards (linked to list), recent solicitations table.
sales/search_results.html — “Results for: {query}” and table (Sol#, NSN, Nomenclature, Return By, Status, Open).
sales/base.html — Topbar search form, dropdown div, typeahead script (300 ms debounce, fetch JSON, click-outside/Escape close), and Dashboard nav link.
sales/solicitations/list.html — Bucket tab strip (All Active, SDVOSB, HUBZone, Growth, Skip with counts), hidden bucket in filter form, Bucket column, Sol# links to detail, pagination via filter_querystring, status badges aligned with new status values.
7. View exports (sales/views/__init__.py)
Dashboard imported from dashboard module; solicitation_detail, no_bid, global_search exported.
Note: The detail template links to the supplier with {% url 'suppliers:supplier_detail' match.supplier.id %} (suppliers app’s detail view). The Build Bid link is the placeholder /sales/bids/<sol#>/build/ and “Send RFQ” / “Send All RFQs” use # until Session 4.

You can run the app and click through Dashboard → Solicitations (with bucket tabs) → a Sol# → detail (Overview/Matches) and use the topbar search and No-Bid action.


## Summary of what was implemented for Session 4 — DIBBS Sales App (RFQ dispatch pipeline and supplier quote entry):

Output checklist
sales/models/rfq.py — Added to SupplierRFQ: email_message_id, follow_up_sent_at, follow_up_count, notes, declined_reason; email_sent_to is now nullable; added PENDING to status choices. SupplierContactLog was already present; no structural change.
sales/models/cages.py — Added smtp_reply_to to CompanyCAGE.
sales/models/__init__.py — Already exports SupplierContactLog, CompanyCAGE; no change.
Migration — 0004_rfq_extra_fields_and_cage_smtp created and applied.
Solicitation.dibbs_pdf_url — Property added in sales/models/solicitations.py.
sales/services/email.py — New module with send_rfq_email() and send_followup_email() (supplier email: contact → primary_email → business_email; default CAGE for From/Reply-To; contact log and status updates).
sales/views/rfq.py — New module with: rfq_pending, rfq_send_batch, rfq_send_single, rfq_sent, rfq_mark_no_response, rfq_mark_declined, rfq_send_followup, rfq_enter_quote, and quote_select_for_bid.
sales/views/solicitations.py — solicitation_detail updated: rfqs, quotes, contact_log, default_markup_pct/suggested_bid for quotes, match annotation for rfq_sent/rfq_status_display, and pdf_url from dibbs_pdf_url.
sales/views/__init__.py — Exports all new RFQ and quote views.
sales/urls.py — New RFQ and quote URLs added (pending, sent, send single/batch, quote, followup, no-response, declined, quote-select-for-bid).
sales/templates/sales/base.html — “RFQ Center” nav link added between Solicitations and Import.
sales/templates/sales/rfq/pending.html — New: “RFQ Pending — Review & Send”, summary bar, groups by solicitation/line with return-by and days remaining, supplier table with tier/score and Send RFQ / Send All / Send Selected.
sales/templates/sales/rfq/sent.html — New: “Sent RFQs” with Overdue / Urgent / Awaiting / Responded / Closed sections and row actions (Enter Quote, Follow Up, No Response, Declined).
sales/templates/sales/rfq/quote_entry.html — New: context card, Unit Price, Lead Time, live Suggested Bid (JS with default_markup_pct), optional Part Number / Qty / Notes (collapsed), Save Quote, Ctrl+Enter to submit.
sales/templates/sales/solicitations/detail.html — Matches tab: Send RFQ forms (single + batch), status badge when RFQ already sent; RFQs tab: table with Enter Quote / Follow Up / No Response / Declined; Quotes tab: table with Suggested Bid and “Use This Quote”; Activity feed at bottom; “Use This Quote” POSTs to quote_select_for_bid.
Notes
Email — The project has “Email settings removed” in STATZWeb/settings.py. send_rfq_email and send_followup_email use CompanyCAGE.smtp_reply_to or settings.DEFAULT_FROM_EMAIL or noreply@localhost. To actually send mail, configure EMAIL_* and optionally DEFAULT_FROM_EMAIL in settings (and ensure a default CompanyCAGE exists with is_default=True and optionally smtp_reply_to).
Supplier email — Resolved in this order: supplier.contact.email (primary contact FK), then supplier.primary_email, then supplier.business_email (per suppliers.models).
Suggested bid — unit_price × (1 + default_markup_pct / 100); default_markup_pct comes from the default CompanyCAGE (default 3.50).
Quote select — “Use This Quote” sets is_selected_for_bid=True on that quote and redirects back; no automatic clearing of other quotes for the line.
Run python manage.py check (already run) and hit /sales/rfq/, /sales/rfq/sent/, and a solicitation detail (Matches / RFQs / Quotes tabs) to verify the flow.


## Summary of what was implemented for Session 5:

Session 5 — Completed
1. RFQ Center (3-panel)
rfq_center (/sales/rfq/center/) — Renders the 3-panel shell with left-panel queue grouped as Overdue / Urgent / Awaiting / Responded / Closed; supports ?rfq= for direct link; left-panel live search.
rfq_center_detail (/sales/rfq/center/<id>/detail/) — Returns the center-panel HTML fragment for the selected RFQ (for fetch()).
Templates: sales/rfq/center.html, sales/rfq/partials/center_panel.html.
Quote entry: Right panel slides in on “Enter Quote”; form submits via fetch(); rfq_enter_quote returns JSON when from_center or X-Requested-With: XMLHttpRequest; on success the center panel refreshes and the row moves to Responded.
2. Bid Center
bids_ready (/sales/bids/ready/) — Lines with quotes and no submitted bid; shows best quote, suggested bid @ default markup, [Build Bid].
bid_builder (/sales/bids/<sol#>/build/) — Builds/edits a GovernmentBid; quote choice via “Use This Quote” (uses bid_select_quote so only one quote per line is selected); sections 01–06 and live margin pill; Save Draft / Mark Ready to Export.
bid_select_quote (POST) — Sets is_selected_for_bid=True on the chosen quote and clears it on other quotes for the same line; redirects back to bid builder.
bids_export_queue (/sales/bids/export/) — Lists DRAFT bids for BID_READY solicitations; checkboxes and “Export Selected as BQ File”.
bids_export_download (POST) — Calls generate_bq_file(bid_ids); on validation error re-renders export queue with export_errors; on success returns BQ file and sets bids to SUBMITTED and solicitations to BID_SUBMITTED.
3. BQ export service (sales/services/bq_export.py)
BQExportError — Exception with .errors list.
validate_bid_for_export(bid) — Checks unit_price, delivery_days, quoter_cage, manufacturer_dealer, mfg_source_cage for DD/QD, bid_remarks for BI vs BW/AB, part number when item_description_indicator in 'PBN'.
generate_bq_file(bid_ids) — Loads bids; validates all; for each bid uses line.bq_raw_columns as the 121-column template and overlays company-filled columns (from GovernmentBid and CompanyCAGE); returns CSV content.
4. Supplier capability views
supplier_list (/sales/suppliers/) — Search by name/CAGE; filter “Has NSN”; table with NSN/FSC counts and [View].
supplier_detail (/sales/suppliers/<id>/) — Tabs: Profile, Capabilities (NSN/FSC tables with Remove), Quote History.
supplier_add_nsn / supplier_add_fsc — Forms to add NSN (13 digits, match_score, notes) or FSC (4-char code); NSN created with source='manual'.
supplier_remove_nsn / supplier_remove_fsc (POST) — Delete capability and redirect to supplier detail.
5. Models and migration
SolicitationLine — bq_raw_columns (JSONField) for BQ export template.
GovernmentBid — payment_terms, material_requirements, hazardous_material, part_number_offered_code, part_number_offered_cage, part_number_offered.
Importer — Persists bq_raw_columns from ParsedBatchQuote.raw_columns when a BQ row exists for the line.
6. URLs and nav
New routes for RFQ center, bid center, export, and suppliers (including remove NSN/FSC).
base.html — “RFQ Center” links to /sales/rfq/center/; “Bid Center” and “Suppliers” added; active state includes the new URL names.
7. Templates
Bids: ready.html, builder.html, export_queue.html.
Suppliers: list.html, detail.html, add_nsn.html, add_fsc.html.
Note on BQ export
Export requires SolicitationLine.bq_raw_columns to be set. That happens when the line is created/updated from an import that includes the BQ file. For lines that predate this or that come from IN-only imports, export will raise BQExportError with a message to re-import with the BQ file.

Migration 0005_bq_raw_columns_and_bid_fields has been applied. You can run the app and use RFQ Center, Bid Center (Ready to Bid → Build Bid → Mark Ready → Export), and Suppliers (list → detail → add/remove NSN and FSC).


## Summary — Session 6: Missing view functions
Task 1 — sales/views/rfq.py (no new views; existing ones updated)
rfq_center

default_markup_pct is now a Decimal (from CompanyCAGE or 3.50).
No other changes; grouping and rfq_groups_display were already correct.
rfq_center_detail

Context extended with:
default_markup_pct (Decimal)
suggested_bid: best quote’s unit_price × (1 + markup/100), or None if no quotes
ApprovedSource is still filtered by NSN (no line on the model).
Task 2 — sales/views/bids.py (existing file updated)
bids_ready

bid_lines sorted by solicitation.return_by_date (asc), then line.id.
bid_builder

POST: selected_quote_id is read from POST and used to set bid.selected_quote when saving.
Context now includes bid (same as existing bid for the line) in addition to existing_bid.
bid_select_quote

Redirect is to request.POST.get('next') or sales:bids_ready (no longer always to bid_builder).
bids_export_queue

export_errors taken from request.session.pop('export_errors', []).
Export list ordered by solicitation__return_by_date.
select_related set to solicitation, line, selected_quote, selected_quote__supplier.
bids_export_download

On BQExportError: errors stored in request.session['export_errors'] and redirect to sales:bids_export_queue (no re-render).
Download filename: BQ_export_YYYY-MM-DD.txt.
Task 3 — sales/views/suppliers.py (existing views updated, backfill_nsn unchanged)
supplier_list

Pagination: 50 per page via Paginator; context includes page_obj and suppliers (current page).
supplier_detail

fsc_capabilities ordered by fsc_code.
quote_history: select_related('line__solicitation', 'rfq'), order_by('-quote_date')[:50].
Context includes active_tab from request.GET.get('tab', 'profile').
rfq_history removed from context (per spec).
supplier_add_nsn

POST: NSN normalized (13 digits); get_or_create with part_number, notes, source='manual', match_score=100.
Redirect: sales:supplier_detail with ?tab=capabilities.
Context: error (string or None) and errors (e.g. {"nsn": error}) so existing templates still work.
supplier_add_fsc

POST: fsc_code validated as 4 alphanumeric and uppercased.
Redirect: sales:supplier_detail with ?tab=capabilities.
Context: error and errors (e.g. {"fsc_code": error}).
supplier_remove_nsn / supplier_remove_fsc

Redirect: sales:supplier_detail with ?tab=capabilities.
backfill_nsn

Unchanged.
Unused SupplierRFQ import removed.

Task 4 — sales/views/__init__.py
No changes; all required views were already imported and exported.
Task 5 — sales/templates/sales/base.html
No changes; Bid Center and Suppliers links and RFQ Center active state (including rfq_center and rfq_center_detail) were already in place.
Checklist

sales/views/rfq.py — rfq_center and rfq_center_detail updated (context + Decimal).
sales/views/bids.py — All five bid views updated (ordering, session errors, redirects, filename, bid/selected_quote_id).
sales/views/suppliers.py — backfill_nsn unchanged; list/detail/add_nsn/add_fsc/remove_nsn/remove_fsc updated per spec.
sales/views/__init__.py — Exports already correct.
sales/templates/sales/base.html — Nav already correct.
Templates were not modified. Linting passes on the updated view files.


## Summary of what was implemented for Session 7:

Task 1 — Model migration: hubzone_requested_by
sales/models/solicitations.py: Added hubzone_requested_by to Solicitation (after bucket_assigned_by) with max_length=100, blank=True, default='', and the given help_text.
Migration: Created and applied sales/migrations/0006_add_hubzone_requested_by.py; migrate completed successfully.
Task 2 — Bulk bucket reassignment UI
sales/views/solicitations.py: At the top of solicitation_list, added a POST branch that handles action=reassign_bucket: reads sol_ids, new_bucket, and bucket_note, validates bucket, updates bucket, bucket_assigned_by, and hubzone_requested_by, then redirects with a success message.
sales/templates/sales/solicitations/list.html:
Wrapped the table in <form id="bulk-form"> with CSRF and hidden action="reassign_bucket".
Added the bulk toolbar (hidden by default) with count, bucket <select>, note input, Reassign and Clear buttons.
Added a checkbox column: header “select all” and per-row name="sol_ids" value="{{ sol.id }}".
Closed </form> after the pagination block.
Added the inline script for updateToolbar(), select-all, and clearAll().
Empty row colspan set to 10.
Task 3 — Settings page: CompanyCAGE
sales/views/settings.py (new): settings_index (redirect to CAGE list), settings_cages, settings_cage_add, settings_cage_edit, and _cage_from_post() with the specified fields and choice defaults; add/edit pass affirmative_choices and prev_contracts_choices in context.
sales/templates/sales/settings/cages.html (new): Extends sales/base.html, list of CAGEs with Add CAGE, messages, empty-state CTA, and table with Edit links.
sales/templates/sales/settings/cage_form.html (new): Add/Edit form with CAGE code, company name, reply-to email, markup %, SB/affirmative/previous/ADR selects, and is_default/is_active checkboxes; defaults for new record (e.g. B, Y6, Y4, A) and “← Settings” back link.
sales/urls.py: Registered settings_index, settings_cages, settings_cage_add, settings_cage_edit and the four settings paths.
sales/views/__init__.py: Exported the four settings views.
sales/templates/sales/base.html: Added a “Settings” nav link after Import, active when 'settings' is in request.resolver_match.url_name.
Task 4 — RFQ overdue badge
sales/context_processors.py (new): rfq_counts(request) returns overdue_rfq_count for authenticated users (count of SupplierRFQ with status='SENT' and line__solicitation__return_by_date__lt=today).
STATZWeb/settings.py: Appended 'sales.context_processors.rfq_counts' to TEMPLATES[0]['OPTIONS']['context_processors'].
sales/templates/sales/base.html: On the “RFQ Center” nav link, added a red badge showing {{ overdue_rfq_count }} when non-zero.
Task 5 — No-Bid on solicitation detail
sales/templates/sales/solicitations/detail.html: In the Bid tab (active_tab == 'bid'), added a “No Bid” form that POSTs to sales:no_bid with a confirm dialog, shown only when status is not NO_BID, BID_SUBMITTED, WON, or LOST. The existing “Mark No-Bid” in the header was left as-is; the new button is in the Bid tab as requested.
Pre-session checklist (your side):

Migration has been run.
Configure email in STATZWeb/settings.py (EMAIL_BACKEND, EMAIL_HOST, etc.) when you are ready to send mail.
Create the first CompanyCAGE via Settings → Company CAGEs → + Add CAGE (or Django admin) so bid builder and BQ export work.


## File Audit — March 2026 (post Session 7)

Verified all Session 7 items against actual source files:

### ✅ Confirmed Complete (Session 7)
- `hubzone_requested_by` field on `Solicitation` model — confirmed in `sales/models/solicitations.py` + migration `0006_add_hubzone_requested_by.py`
- Bulk bucket reassignment UI — checkboxes + toolbar in `solicitations/list.html`, POST handler in `views/solicitations.py`
- Settings page (CompanyCAGE) — `views/settings.py` + templates `settings/cages.html` + `settings/cage_form.html`; URLs registered in `urls.py`; views exported in `views/__init__.py`
- RFQ overdue badge — `context_processors.py` present; `sales.context_processors.rfq_counts` registered in `STATZWeb/settings.py`; red badge in `base.html`
- No-bid action on solicitation Bid tab — confirmed in `detail.html` lines 326+
- Settings nav link — confirmed in `base.html`

### ✅ Built in post-S7 audit session
- Import History page — `/sales/import/history/` — `views/imports.py` (`import_history`), `templates/sales/import/history.html`; paginated table of `ImportBatch` records; "View Import History →" link added to upload page header; nav active state added to Import tab
- Bid History page — `/sales/bids/history/` — `views/bids.py` (`bids_history`), `templates/sales/bids/history.html`; paginated table of submitted `GovernmentBid` records; POST action to mark solicitation WON/LOST; "Bid History" nav link added to base.html; both routes registered in `urls.py` and exported from `views/__init__.py`

### Phase 3 items (intentionally deferred, expected to be missing)
- BQ export full 121-column validation ruleset
- Win/loss reporting and analytics
- Price history per NSN trending charts
- Bulk no-bid actions
- Role-based access control
- Dark mode