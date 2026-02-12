# Contracts App — Current State Summary

This document summarizes what the **Contracts** app currently does. Use it as a baseline for discussing what to change. Add your notes in the **User feedback** section at the end.

---

## 1. Purpose and Scope

The Contracts app is a full-lifecycle contract management system. At the core:

- A **Contract** has header data (number, PO, buyer, dates, value, status, etc.) and belongs to a **Company**.
- A **Contract** has one or more **CLINs** (Contract Line Items). Each CLIN has supplier, NSN, quantities, dates, financials, and can have shipments and payment history.
- **Suppliers** have contacts, addresses, certifications, and classifications (separate app integration).
- **Notes** and **Reminders** attach to Contract, CLIN, or IDIQ via Django’s ContentTypes (generic relations).
- **Payment history** is tracked at both Contract and CLIN level with audit trail.

---

## 2. Data We Manage

### 2.1 Contracts

- **Create**: `/contracts/create/` — ContractForm; optional DD1155 extraction to prefill CLINs; sequence numbers for PO/Tab.
- **View/Manage**: `/<pk>/` — Single “contract management” page: header, CLIN list, acknowledgment for selected CLIN, notes in tabs (Contract + one tab per CLIN), Gov Actions + Log Fields tabs, expedite, options; CLIN list includes Item Type, Quoted Due Date, supplier link; "Contract Search" button to jump to another contract; supplier links go to suppliers app. Options: update, close, cancel, review.
- **Update**: `/<pk>/update/` — Full contract edit form.
- **Close / Cancel**: `/<pk>/close/`, `/<pk>/cancel/` with dedicated forms (reason, date).
- **Review**: `/<pk>/review/` and mark-reviewed; toggles for expedite and other flags via API.

Key contract fields: `contract_number`, `po_number`, `tab_num`, `buyer`, `contract_type`, `award_date`, `due_date`, `status`, `contract_value`, `plan_gross`, `special_payment_terms`, `supplier`, `idiq_contract`, review and assignment fields, company.

### 2.2 CLINs

- **Create**: `/contracts/clin/new/` or `/contracts/contract/<id>/clin/new/` — ClinForm (contract, item number, type, supplier, NSN, value, dates, etc.).
- **View**: `/contracts/clin/<pk>/` — CLIN detail: header, notes, acknowledgment, shipments, payment history, splits.
- **Edit**: `/contracts/clin/<pk>/edit/` — Full CLIN form.
- **Acknowledgment**: `/contracts/clin/acknowledgment/<pk>/edit/` — PO to supplier, reply, PO to QAR with dates/users.
- **Delete**: `/contracts/clin/<pk>/delete/`.
- **Quick toggles**: e.g. acknowledgment booleans via API; some field updates via `update_clin_field` API.

CLINs have: `item_number`, `item_type`, `supplier`, `nsn`, `item_value`, `unit_price`, `order_qty`, `ship_qty`, `due_date`, `supplier_due_date`, `ship_date`, late flags, payment-related fields, `special_payment_terms`, and generic relations for notes and payment history.

### 2.3 Notes

- **Add**: Form at `note/add/<content_type_id>/<object_id>/` or via **API** `api/add-note/` (supports optional reminder).
- **Edit**: `note/update/<pk>/` — NoteForm; redirects back to contract management by object_id.
- **Delete**: `note/delete/<note_id>/` — Permission: creator or staff; AJAX returns updated notes list.
- **Tabbed view**: Contract management page shows notes in tabs: Contract tab (contract-level notes), then one tab per CLIN (e.g. CLIN 0001, CLIN 0002) showing that CLIN's notes. CLIN tab content loads via AJAX when switching CLINs.

Notes are generic: they attach to Contract, CLIN, or IDIQ. They have `note` (text), `company`, and audit fields.

### 2.4 Reminders

- **List**: `/contracts/reminders/` — filters by Status (All/Pending/Completed), Time Period (Upcoming, Due, Overdue, All Time).
- **Sidebar**: Contract base template has Reminders panel with 0–7 "Future days" dropdown (UserSettings); past reminders always shown; Upcoming badge for future reminders. Scoped by active company (reminders do not cross companies).
- **Add**: `/contracts/reminder/add/` or from a note (`add_reminder` with optional `note_id`).
- **Toggle complete**, **Delete**, **Edit**, **Mark complete** — dedicated URLs.

Reminders can be standalone or tied to a Note (and thus indirectly to a contract/CLIN).

### 2.5 Values and Financials

- **Contract value / Plan gross**: Updated via **Payment History** API when adding payment history entries (totals are recalculated and written to Contract).
- **CLIN financials**: Same idea — payment history API for item_value, quote_value, paid_amount, wawf_payment; CLIN totals updated from history.
- **Payment History**: Popup/inline UI for contract and CLIN; GET/POST to `api/payment-history/<entity_type>/<entity_id>/<payment_type>/`. Audit (created_by, dates) is stored.
- **Splits**: Contract-level splits (e.g. PPI/STATZ) — create/update/delete via API; displayed on contract/CLIN views and in Contract Log.

### 2.6 Other Contract-Related Data

- **Acknowledgement letters**: Per CLIN; create/edit letter; generate/view doc.
- **Shipments**: Per CLIN (ClinShipment); create/update/delete via API; displayed in CLIN detail/partials.
- **Folder tracking**: Contracts can be placed in “stacks” with status (COS, PACK, PROCESS, W4QAR, etc.); add/close/toggle highlight; search contracts; export.
- **IDIQ**: IDIQ contracts and details (NSN/supplier); separate detail/update/create/delete views.
- **Companies**: CRUD for companies (superuser); used for multi-tenant filtering.
- **Contacts / Addresses**: Stored in contracts app; list/detail/create/update/delete and address selector; used by suppliers and elsewhere.
- **Code tables**: Admin for lookup tables (e.g. status, type, buyer, clin type).

---

## 3. Viewing and Searching Data

- **Dashboard**: `/contracts/` — Contract lifecycle dashboard: search with Open/Closed/Both filter (Both default), open/overdue/on-time counts, due soon, past due, pending acknowledgment, in production, shipped not paid, fully paid, last 20 contracts, buyer breakdown, suppliers. Links to metric detail and export.
- **Metric detail**: Date range and metric (e.g. contracts due, new contracts); list of contracts and export.
- **Contract Log**: `/contracts/log/` — List of CLINs (paginated) with filters/search; shows contract and CLIN info, splits (PPI/STATZ), acknowledgment; export to CSV/Excel and export-time estimate.
- **Contract search**: `/contracts/search/` — Autocomplete search by contract number or PO; supports `status` param (open/closed/both). Used by dashboard and contract-details jump modal.
- **Folder tracking**: Dedicated view with contract search and stack management.
- **Finance audit**: Finance audit view by contract.
- **Supplier views**: List, search, detail with contracts and CLINs.

So “viewing” is spread across: dashboard, contract management page, CLIN detail, contract log, folder tracking, finance audit, and supplier detail.

---

## 4. How Updates Happen Today

| What | How |
|------|-----|
| Contract header | Full form at `/<pk>/update/`; some toggles (e.g. expedite) via API. |
| CLIN header | Full form at `clin/<pk>/edit/`; some fields via `api/clin/<id>/update-field/`. |
| Contract/CLIN values | Largely through Payment History API (add entry → backend updates contract_value/plan_gross or CLIN totals). |
| Notes | Add (form or API), edit (form, redirect to contract management), delete (with AJAX refresh). |
| Reminders | List/add/edit/delete/toggle from reminder URLs. |
| Acknowledgment | Toggle endpoints + acknowledgment letter form. |
| Splits / Shipments | API-only create/update/delete. |

So there is a mix of full-page forms, modals, and API-driven updates; no single “quick edit” pattern for all fields.

---

## 5. Technical Structure (Brief)

- **Models**: `contracts/models.py` — Contract, Clin, Note, Reminder, PaymentHistory, ClinShipment, ContractSplit, FolderTracking, FolderStack, AcknowledgementLetter, ClinAcknowledgment, GovAction, Address, Company, plus code tables and IDIQ.
- **Views**: Modular under `contracts/views/` (contract_views, clin_views, note_views, reminder_views, finance_views, payment_history_views, api_views, dashboard_views, contract_log_views, folder_tracking_views, etc.).
- **Forms**: `contracts/forms.py` — ContractForm, ClinForm, NoteForm, ReminderForm, and others; BaseFormMixin for styling.
- **URLs**: `contracts/urls.py` — Many named routes for dashboard, CRUD, APIs, reminders, notes, folder tracking, IDIQ, companies, code tables.
- **Templates**: `contracts/templates/contracts/` — contract_management.html (main hub), contract_detail, contract_form, clin_detail, clin_form, partials (notes_list, note_modal, clin_shipments, contract_splits, payment_history_popup), includes (modals, menu items), and feature-specific templates.
- **Frontend**: TailwindCSS; AJAX for notes, payment history, toggles, and some dropdowns; modals for notes and payment history.

---

## 6. Security and Conventions

- `@conditional_login_required` (or `@login_required`) on views.
- Company-scoped data where applicable (`request.active_company`).
- Note delete restricted to creator or staff.
- CSRF, parameterized queries, and audit fields (created_by, modified_by, etc.) in use.

---

## 7. Gaps and Friction (Observations for Discussion)

- **Many entry points**: Contract vs CLIN vs dashboard vs log vs folder tracking — “where do I do X?” can be unclear.
- **Notes**: Edit redirects to contract management by object_id; combined contract+CLIN notes only on contract management with a selected CLIN.
- **Values**: Contract/CLIN value updates are tied to Payment History; no single “edit value” flow for all fields.
- **Mixed UX**: Some full-page forms, some modals, some API-only; inconsistent “quick edit” behavior.
- **Viewing**: Key data is spread across dashboard, contract management, CLIN detail, contract log, and folder tracking; no one “contract + CLINs + notes + financials” view.

---

## 8. User Feedback (Your Notes)

*Add below what users like and what they don’t like. This will drive the “what we’re changing into” and the TODO list.*

### What users like

- Its Web based.
- New data structure make more sense

### What users don’t like / pain points

- To many click to see data.
- Notes are mixed together and I can see what is what.
- UI is very confusing needs to be simpler more user friendly
- Users don't open it because they are used to the old app
- **From user feedback:** In the new app "all the notes, whether contract or CLIN related are bunched together and it takes longer to find the note that I am looking for." In the old app "almost everything we need is at our fingertips from the contract page" (e.g. latest notes visible from opening page when responding to DLA/DCMA calls).
- **From user feedback:** Reminders in the new app show all as past due; user isn't sure how to look for future flags or work flags in advance. Question: do we need a "reminder title" when adding reminders?
- **From second feedback:** Search brings up everything with a large list; user wants Open / Closed / Both filter. Gov Actions (PARS, Quality Notices, Litigation) not found — planned for "Future Section" on main contract screen. CLIN line due date may be showing contract due date instead of Quoted Due Date. Contract documents hard to get to (popup with Explorer link vs old app clickable folder); docs are in SharePoint. Email addresses for POs/correspondence not findable from contract/CLIN — currently under Supplier info in old app; need link from CLIN to supplier page.

### What we want to change into (goals)

- We want a brand new user to be able to open the Contracts app, and be able to click around and see the information they expect to see.
- We want to limit the nuber of clicks to get to important data.
- Notes are probably some of the most important data in the App.  The Program is about the Contracts but the Notes are what manage the contracts.
- I want the user to be able to click on a piece of data and get a window to update it.
    - What I really really want is a transaction system for updating data.  The user clicks on a field they make their change and we store a transaction in a table (field, Old data, new data, user, date of change.)

### Feedback log (verbatim from users)

*Keep raw feedback here so nothing is lost. Summaries go into the bullets above.*

**First user feedback (Discovery + Adoption):**

- **First thing when opening (old app):** Usually search for a particular contract in response to an email, OR work my flags — click the bell with my flags, search for that contract, perform the action required by the flag.
- **3–5 daily tasks:** Add a note; Check my flags (doesn't check late contracts separately — flags contracts for follow-up); Track PARs submitted; Search for a specific document; Enter quoted due dates when creating a new PO.
- **Find one contract:** Search by last 4 digits of contract number. "Just a couple of clicks."
- **Notes:** This user uses both contract-level and CLIN-level (e.g. FAT CLIN → notes under that CLIN). "Chad prefers contract-level."
- **Fear about new app:** "More clicks required to get to the information. Right now, almost everything we need is at our fingertips from the contract page. If I receive a call from DLA or DCMA I am able to pull up the contract quickly and see the latest notes right from the opening page." In the new app, notes are "bunched together" and it takes longer to find the note she's looking for.
- **Reminders:** In the new app reminders show all as past due; no new ones; not sure how to look for future flags or work flags in advance. Question: "Under add reminders, I'm not sure that we need to have a reminder title? Chad, your thoughts."

**Second user feedback (search, Gov Actions, due date, documents, emails) — with your answers:**

- **Search filter:** "The search bar doesn't let us choose Open or Closed or Both. This is very handy when searching for a contract. Right now it brings up everything and there is a large list to scroll through." — *Your answer:* She is doing a very vague search, but Open / Closed / Both is a pretty easy filter to add.
- **Gov Actions:** "I'm not able to find the Gov Actions area. This is the area where we keep track of PARS, Quality Notices and Litigation statuses." — *Your answer:* This section has not been added yet; it is intended for the open area on the Main Contract Screen where it says "Future Section".
- **Due date on CLIN line:** "The due date that shows with the CLIN Line should be the Quoted Due Date. Right now, it is showing the contract due date." — *Your answer:* Will look into it; pretty sure we are showing the date in the CLIN table (verify which field is displayed).
- **Contract documents:** "The contract documents are hard to get to. When I click to review a contract a pop-up window comes up and tells me to open Windows Explorer and paste in the link to get to the folder. Right now, the folder allows us to click and all the documents are there." — *Your answer:* In Access they could open documents/folders without the same security constraints. Our documents are stored in SharePoint; need to explore what we can do about linking to there.
- **Email addresses for POs and correspondence:** "I can't figure out how to get to the email addresses to send the new PO's and correspondence to. Right now, it is under Supplier info." — *Your answer:* We need to link the Suppliers in the CLIN section to their supplier page that has that information.

---

## 9. Getting Useful Feedback — Questions & Adoption

*You need users in the new app before you can get real feedback. Below: questions to sharpen feedback, and ways to get users there.*

### 9.1 Questions to Uncover Useful Feedback

Use these when you talk to users (or when you wear the "user hat"). They turn vague "it's confusing" into actionable "do this instead."

**Discovery (what do they actually do?)**

- What is the **first thing** you do when you open the Contracts app (or the old one)? What are you trying to find or do?
- In a typical day, what are the **3–5 tasks** you do most? (e.g. "Check due dates," "Add a note," "Update a value," "See who's late.")
- When you need to **find one contract**, how do you do it today? How many clicks or steps?
- When you need to **add or read notes** for a contract, where do you expect to see them? Contract-level only, CLIN-level only, or both in one place?

**Pain (what's "too many clicks" in practice?)**

- Can you walk me through **one real task** you did recently? Where did you click, and where did you get stuck or annoyed?
- What's the **one screen or action** you wish you could do in a single click from the home/dashboard?
- For **notes**: What would make it obvious "what is what"? (e.g. labels like "Contract note" vs "CLIN 0001 note," filters, separate sections?)

**Adoption (why they don't open the new app)**

- What does the **old app** do that you're afraid the new one doesn't? (Even if it's wrong, it's real.)
- If the new app opened **by default** when you go to Contracts, what's the first thing you'd try to do? Would you succeed?
- What would need to be true for you to **choose** the new app over the old one? (Speed, one specific feature, less clutter, etc.)

**Goals (what "good" looks like)**

- If a **new person** joined tomorrow, what should they be able to do in the Contracts app without training?
- When you **update a value** (e.g. contract value, due date), do you care about seeing who changed it and when? (Feeds into the transaction/audit goal.)

You don't need to ask every question. Pick 3–5 that match your biggest unknowns (clicks, notes, adoption) and use the answers to add bullets under Sections 8.1–8.3.

---

### 9.2 How to Get Users Into the New Program So You Get Feedback

**Your situation**

- **Old program**: Access database with forms, connected to a SQL database.
- **New program**: This Django app, with a different database and completely different schema.
- **Data migration**: You run migrations from the old database to the new one **weekly**. You've spent weeks making the migration **update** the new schema (merge/upsert) rather than wipe-and-reload, so data entered in the new app isn't lost when old data is synced in.
- **Only 5 users** total. One user tried the new app and said it was "too many clicks."
- You **already try to collect feedback** whenever you can.

So migration is already in place (weekly sync). The blocker to adoption is **UX and habit** (too many clicks, users used to the old app), not missing data. The sequence is: **reduce clicks and simplify UI → get users to try again.** Below is adjusted for that.

---

**Make the new app the default**

- Data is already flowing into the new app weekly (update migration, not wipe-and-reload). So from a **data** standpoint, the new app could be the default; users would see up-to-date data (within the weekly sync).
- The reason not to switch yet is **adoption**: users prefer the old app or find the new one "too many clicks." So the lever is **improving the new app's UX** so that making it the default (or asking users to use it) is realistic. Once key paths have fewer clicks and clearer notes, you can make the new app the default and keep Access as "Legacy" only if needed.

**Lower the bar to try it (with 5 users and "too many clicks")**

- You already got one concrete signal: **"too many clicks."** Use that. Pick the **one task** that user does most (e.g. "open a contract and read notes") and design the new flow so it's **fewer clicks than today**. Then ask her to try only that task again and compare.
- **Click-count exercise**: For one real task, write down: "In the old app this is 4 clicks; in the new app it's 7." That makes "too many clicks" specific and gives you a target (e.g. get it to 3).
- With only 5 users, **each person's feedback is high-value**. If one person tries and stops, the next step is: fix the biggest click/confusion win, then ask the same person (or another) to try that single task again. You're not looking for a big pilot—you're looking for "try this one path, did it feel better?"

**Collect feedback (you're already doing it)**

- Keep doing it. With 5 users, **write down every comment** (e.g. in Section 8 or a short "feedback log"). "Too many clicks," "notes are mixed," "don't open it because used to old app"—each of these is already in your doc and can drive the TODO list.
- If helpful: a **tiny in-app link** ("Feedback" or "Something wrong?") that opens an email or form with "What were you trying to do? What was confusing?" so you capture the exact scenario when it happens.

**Frame the ask**

- Once you've reduced clicks on one or two key paths: "We shortened the path for [X]. Can you try it and tell me if it's better or what still feels like too many clicks?" That gives you a concrete follow-up instead of "please use the whole app."

---

### 9.3 One-Line Summary

**To get useful feedback in your situation:** (1) Weekly update migration is already in place, so the blocker is UX and habit, not data. (2) Use "too many clicks" as the first design goal—pick one task, reduce clicks, then ask a user to try that task again. (3) Keep capturing every piece of feedback (you already do) and write it into Section 8 or a log so it drives the TODO list.

---

## 10. TODO List

*All contract-app streamlining work lives here. Check off as you go. Add new rows as needed.*

**Progress:** 13 of 20 items done. Recent completions: Filter reminders by company (context processor), Reminder sidebar 0–7 days ahead (UserSettings).

### Find contract / fewer clicks

- [x] **Search by last 4 of contract number** — Implemented: `contract_number__icontains` already matches substrings; typing last 4 digits (e.g. 1295) finds the contract. Placeholder/hint text updated to mention "last 4 digits" on dashboard, contract search modal, folder tracking, contract log, and finance audit.
- [x] **Search filter: Open / Closed / Both** — Implemented: Contract Dashboard search has Open/Closed/Both radio buttons (Both default); folder tracking search modal same; contract_search API supports status param; company-scoped.
- [x] **Jump to contract from contract details** — Implemented: "Contract Search" button next to "Back to Dashboard" opens modal with search box, Open/Closed/Both radios, autofill; select a contract → navigate to it; Cancel closes modal.
- [ ] **Contract page = everything at fingertips** — Opening a contract should show key info and latest notes without extra clicks (DLA/DCMA call scenario). Reduced padding/margins on contract details page to fit more information.
- [ ] **Reduce clicks on one pilot task** — Pick one task (e.g. "find contract + see latest notes"), count clicks in new app, reduce until it matches or beats old app; then have user retry.

### Notes

- [x] **Separate contract vs CLIN notes** — Implemented: Notes in tabbed UI. Contract tab shows contract notes; one tab per CLIN (e.g. CLIN 0001, CLIN 0002) shows that CLIN's notes. CLIN tab content updates when switching CLINs or clicking a CLIN tab.
- [x] **Notes visible from contract opening page** — Contract details page is the opening page for a contract; notes tabs are visible by default (Contract + CLIN tabs).

### Reminders / flags

- [ ] **Fix reminders showing all as past due** — Code reviewed; logic is correct (sidebar now has 0–7 days ahead). Likely data migration issue; verify migrated reminder dates.
- [x] **Way to see future flags and work in advance** — Implemented: "Upcoming" filter moved first in Time Period; added hint "Use Upcoming to work flags in advance."
- [x] **Filter reminders by company** — Implemented: context processor now filters by active_company (same as reminders list); reminders do not cross companies.
- [x] **Reminder sidebar: 0–7 days ahead** — Implemented: dropdown (0–7) in reminder side panel; persists via UserSettings; 0 = today only, 1–7 = include that many days ahead; Upcoming badge for future reminders.
- [ ] **Reminder title** — Decide with Chad: required or optional when adding a reminder; simplify form if optional.

### Data / UX (goals from Section 8)

- [ ] **Click-to-edit** — User clicks a field → small window to update value (no full-page form for simple edits).
- [ ] **Transaction log for changes** — Store edits as transactions: field, old value, new value, user, date (audit trail).
- [ ] **New user can find what they expect** — Simplify UI so a brand-new user can open the app and find information without training.
- [ ] **Simplify overall UI** — Fewer entry points, clearer navigation, more user-friendly (from feedback: "UI is very confusing").

### From second user feedback

- [x] **Gov Actions section** — Implemented: Gov Actions tab (unlimited per contract, modal add, delete with confirm); Log Fields tab (status/notes per selected CLIN); replaces "Future Section".
- [x] **CLIN line due date** — Implemented: CLIN table now shows Quoted Due Date (supplier_due_date) with fallback to due_date; column header updated.
- [x] **Contract documents / SharePoint** — Implemented: "Open Documents" link on contract management opens SharePoint folder in browser (built from contract_number + status; Open vs Closed Contracts path). Falls back to "Copy Path" when files_url exists but no SharePoint URL.
- [x] **Do we want to add base URL into the Company table?** — Store the SharePoint document-library base path (or root segment like `V87/aFed-DOD`) per Company so different companies can have different document paths; would support the "Company-specific paths" note in Section 11.
- [x] **Link CLIN to supplier page for emails** — Implemented: supplier name in CLIN table links to `/suppliers/{id}` (suppliers app detail page) for emails and correspondence.
- [x] **Item Type on CLIN line** — Implemented: Item Type column added to CLIN table on contract details page, between Item No and Supplier; shows Production, GFAT, CFAT, PLT, or Miscellaneous.

---

### Recommended Next Tasks

Prioritized by impact and feasibility:

1. **Contract page = everything at fingertips** — High impact for DLA/DCMA call scenario; may overlap with layout work.
2. **Reduce clicks on one pilot task** — Pick a task (e.g. find contract + see notes), measure, reduce; then user retry.
3. **Reminder title** — Decide with Chad; small form change.
4. **Click-to-edit** — Larger effort; addresses "click field → update" goal.
5. **Do we want Company base URL for SharePoint?** — Enables multi-company document paths.

---

## 11. Old System Screen — Interpretation and Update Plan

*Based on the STATZ Tracking (Access) screenshot. Use this as a design reference for what "everything at our fingertips" means to users.*

### 11.1 Interpretation of the Old Screen Layout

The old system presents **one main screen** with everything a user needs for contract management. No tabs or drill-downs—one scrollable view.

**Top — Search and filter**
- Search bar: search by Tab #, PO #, or Contract (* = IDIQ).
- Results table: Tab # | PO # | Contract columns; user selects one row.
- Result count (e.g. "866 Results").
- **Open / Closed / Both** radio buttons — filter by contract status.
- "Refresh Contract" button.

**Left column — Contract-level actions and notes**
- Contract identifier (e.g. DLA Land, PO #, contract number).
- PO Acknowledge Letter section with "Create" button.
- Status toggles with timestamps: PO Sent to Sup, Acknowledged, PO Sent to QAR.
- "Add Note" button.
- Contract-level notes list (e.g. "PAR 1950711 Cancellation 8/29/18" by System, 5/4/2019).

**Middle column — Contract summary and CLIN list**
- Tab #, Award Date, Contract Due (highlighted if late).
- CDD Late Ship checkbox.
- "Add CLIN" button.
- CLIN table: Type | PO # | Sub-Contract | Supplier. One row per CLIN; selecting a row populates the right column.

**Right column — Selected CLIN detail**
- Full CLIN form: Type, Sub PO #, Supplier dropdown, NSN dropdown, I&A, Special Payment Terms, Origin, FOB, Sub Due Date, Order Qty, **Quoted Due Date**, Ship Date, Ship Qty.
- **"Supplier Info"** button — opens supplier/contact details (emails for POs, correspondence) from this context.
- "Add Note" button.
- CLIN-level notes section (separate from contract notes).

**Bottom — Documents**
- Folder path (e.g. `\\STATZFS01\public\...`). Path is visible and used to reach files.
- **Contract Folder Files** — list of PDFs with filename and size (e.g. Bid Package for P-4076.pdf, 315 KB). User can click to open; all documents for the contract are in one place.
- "Old paths are converted in the background" note suggests migration of legacy paths.

**Overall pattern**
- **Single-screen layout**: Search → select contract → see contract + PO ack + contract notes + CLIN list + selected CLIN detail + CLIN notes + documents, all on one page.
- **Contract vs CLIN notes** are in separate areas (left vs right), so "what is what" is clear.
- **Open/Closed/Both** is prominent at the top of search.
- **Supplier Info** is one click from the CLIN form for emails/correspondence.
- **Documents** are reachable from the same screen via path and file list; no separate app or paste step.
- **Quoted Due Date** and **Sub Due Date** are both shown on the CLIN form (CLIN line should reflect Quoted Due Date when that's what users expect).

---

### 11.2 Update Plan (Phased)

**Phase 1 — Quick wins**
1. **Search Open/Closed/Both** — DONE. Dashboard and folder tracking search; contract_search API supports status.
2. **CLIN row due date** — DONE. CLIN table shows Quoted Due Date (supplier_due_date).
3. **Notes layout** — DONE. Tabbed: Contract tab + one tab per CLIN.
4. **Link CLIN to supplier** — DONE. Supplier name links to suppliers app detail page.
5. **Item Type on CLIN line** — DONE. Column added between Item No and Supplier.
6. **Jump to contract** — DONE. Contract Search modal on contract details page.

**Phase 2 — Layout and supplier access**
7. **Single-view layout** — Redesign contract management so the main sections (contract header, PO ack, contract notes, CLIN list, selected CLIN detail, CLIN notes) are visible in one scroll or minimal tabs, similar to the old screen.

**Phase 3 — Documents (SharePoint; pattern identified)**

6. **Documents** — Old system uses network path + file list. **Constraint:** Opening Windows Explorer from a web browser is blocked by system policy (security risk). **SharePoint pattern identified** — we can build a clickable browser URL from the contract number.

**SharePoint URL pattern:**
- Root library: `https://statzcorpgcch.sharepoint.us/sites/Statz/Shared%20Documents/Forms/AllItems.aspx`
- Parent folder (all contract folders): `...?id=%2Fsites%2FStatz%2FShared%20Documents%2FStatz%2DPublic%2Fdata%2FV87%2FaFed%2DDOD&viewid=d4837fde%2D32f5%2D41cc%2Db723%2D09d5f692b2ea`
- Contract folder path segment: `Contract {CONTRACT_NUMBER}` — e.g. `Contract SPE4A0-22-P-1295`, `Contract SPE3SE-26-V-0214`

**Formula:** Base URL + `?id=` + URL-encode(`/sites/Statz/Shared Documents/Statz-Public/data/V87/aFed-DOD/Contract ` + `{contract_number}`) + `&viewid=d4837fde%2D32f5%2D41cc%2Db723%2D09d5f692b2ea`

**Path by status:**
- **Open contracts:** `aFed-DOD/Contract {contract_number}`
- **Closed (and Cancelled) contracts:** `aFed-DOD/Closed Contracts/Contract {contract_number}`

Closed Contracts parent folder (reference): `https://statzcorpgcch.sharepoint.us/sites/Statz/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FStatz%2FShared%20Documents%2FStatz%2DPublic%2Fdata%2FV87%2FaFed%2DDOD%2FClosed%20Contracts&sortField=Modified&isAscending=false&viewid=d4837fde%2D32f5%2D41cc%2Db723%2D09d5f692b2ea`

**Implementation:** Derive the SharePoint folder URL from `contract.contract_number` and `contract.status`. If status is "Closed" or "Cancelled", use the `Closed Contracts` subfolder; otherwise use the root `aFed-DOD` path. Render as an "Open documents" or "Contract folder" link that opens in the browser. User lands on the SharePoint folder; no Explorer, no paste.

**Company-specific paths:** When the contract's Company is different (not the default), the root path changes (e.g. different segment instead of `V87/aFed-DOD`). No example path for other companies yet — will need a Company-to-path mapping when available.

**Phase 4 — Gov Actions**
7. **Gov Actions** — DONE. Gov Actions + Log Fields tabs on contract management; modal add, delete with confirm; Log Fields per selected CLIN.

---

*Raw feedback paste below (also summarized in Section 8 Feedback log):*

- What is the **first thing** you do when you open the Contracts app (or the old one)? What are you trying to find or do?
The first thing I do when I open the Old app is usually search for a particular contract in response to an email I have received. It’s either that or I am working my flags. I click the bell with my flags and search for that particular contract and perform whatever action is required based upon what my flag is for.


- In a typical day, what are the **3–5 tasks** you do most? (e.g. "Check due dates," "Add a note," "Update a value," "See who's late.")
The tasks I do most are Add a note, Check my flags – I don’t check for late contracts separately as I have always flagged my contracts for follow-up. Track PARs that have been submitted. Search for a specific document. Enter Quoted due dates when creating a new purchase order.

- When you need to **find one contract**, how do you do it today? How many clicks or steps?
When I need to find a contract, I search by the last 4 digits of the contract number. It’s just a couple of clicks.

- When you need to **add or read notes** for a contract, where do you expect to see them? Contract-level only, CLIN-level only, or both in one place?
Chad and I differ in how we use notes. I use both contract level and CLIN level to track specific items. If it is related to a FAT CLIN, my notes go under that CLIN. I know Chad prefers to use the contract level notes.

- What does the **old app** do that you're afraid the new one doesn't? (Even if it's wrong, it's real.)
My fear, from playing with the new JVIC database is that there are more clicks required to get to the information. Right now, almost everything we need is at our fingertips from the contract page. If I receive a call from DLA or DCMA I am able to pull up the contract quickly and see the latest notes right from the opening page.

In the new database, all the notes, whether contract or CLIN related are bunched together and it takes longer to find the note that I am looking for.

The reminders in the new database are showing all as past due. I don’t have any new ones and am not sure how to look for future flags a somedays I work flags in advance.

Under add reminders, I’m not sure that we need to have a reminder title? Chad, your thoughts.


**Second feedback (user notes + your answers):** Here are a few more notes from the user. And my answer to her notes.

I noticed that the search bar doesn’t let us choose Open or Closed or Both. This is very handy when searching for a contract. Right now it brings up everything and there is a large list to scroll through.
 - She is doing a very vague search, but Open. Closed, Both is a pretty easy filter.


I’m not able to find the Gov Actions area. This is the area where we keep track of PARS, Quality Notices and Litigation statuses.
 - This section has not been added, it is intended to be in the open area in the Main Contract Screen where it says "Future Section"

The due date that shows with the CLIN Line should be the Quoted Due Date. Right now, it is showing the contract due date.
- I'll have to look into that, but im pretty sure we are showing the date in the CLIN table.

The contract documents are hard to get to. When I click to review a contract a pop-up window comes up and tells me to open Windows Explorer and paste in the link to get to the folder. Right now, the folder allows us to click and all the documents are there.
- They are spoiled becaause MS Access could open the documents and document folders without any security issues.  Our documents are stored in SharePoint, so I don't know what we can do about linking to there.

I can’t figure out how to get to the email addresses to send the new PO’s and correspondence to. Right now, it is under Supplier info.
- I think for this we need to link the Suppliers in the CLIN section to their supplier page that has that information.

