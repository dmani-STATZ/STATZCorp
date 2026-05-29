# intake — Release Notes

## IDIQ Editor: Explicit NSN+Supplier Pairs (2026-05-29)

User-visible changes:

The IDIQ draft editor now shows a single "CLINs" table where each row
is one NSN paired with one Supplier and a Min Order Qty — replacing the
previous two separate sections (Approved NSNs and Approved Suppliers).
Each row finalizes to exactly one IdiqContractDetails record. Two rows
produce two records, not a cross-product.

## IDIQ Editor: Clean Up Contract Details Card (2026-05-29)

User-visible changes:

The Contract Details section of the IDIQ draft editor now only shows
fields relevant to IDIQ contracts: Contract Number, Buyer, Award Date,
and Files URL.
Fields not tracked on IDIQ contracts (Due Date, Contract Value, PR Number,
Plan Gross, Planned Split, NIST, PO Number) are now hidden for IDIQ drafts.
They remain visible for all other contract types (AWD, PO, DO, etc.).

## [Unreleased]

### Added

Supplier name now auto-populated on each CLIN at PDF ingest. The parser
reads "PLACE OF INSPECTION FOR SUPPLIES" from the DLA 1155 — first at the
contract level as a default, then per-CLIN as an override. When found, the
company name pre-fills the Supplier field so analysts can match without
typing. If the block is absent, the field stays blank for manual entry.

Packhouse name now auto-populated in the Packaging section at PDF ingest
from "PLACE OF INSPECTION FOR PACKAGING" using the same drill-down logic.

### Changed

Intake PDF parser is now fully independent of the `processing` app.
`intake/pdf_parser.py` is the intake-owned parser. The
`processing.services.pdf_parser` import has been removed from
`intake/ingest.py`. Intake no longer has a hard dependency on the
processing app for PDF parsing.

Planned Split auto-populates as a plain percentage total (e.g. "100")
derived from the sum of all CLIN split row percentages. Plan Gross
continues to auto-populate from Net Contract GP. Both fields remain
manually editable.

GP Split smart defaults: clicking "+ Add Split" on a CLIN with no
splits pre-fills the first entry as STATZ at 100%. Adding a second
split automatically drops the first to 50%, leaving the new entry
blank for the analyst to fill in. Adding a third or more splits
makes no automatic adjustments.

Finance Lines and GP Split entries now render as individual cards
instead of table rows — each entry shows fields side-by-side in a
light bordered card with a trash button. No data or field names
changed.

Contract Details form reordered to a 2-column layout matching the
desired field groupings: Contract Number / IDIQ Contract, PO / PR Number,
Buyer / Sales Class, Contract Type / Solicitation Type, Award Date / Due Date,
Contract Value, Plan Gross / Planned Split, Files URL / NIST.
CLIN card Contract Data section reordered: Item Number, Item Type, CLIN PO
Number (display-only), IA on top row; FOB full-width; NSN + Due Date;
Quantity / UOM / Unit Price / Total Value.
"INTAKE TYPE" (parser-set, read-only) and "CONTRACT TYPE" (analyst-selected
canonical ContractType FK) are now both visible in the Contract Details
section.

### Added

`canonical_contract_type_id` field added to intake draft data schema
(`_CommonContractFields`). Analyst selects the canonical ContractType
(Bilateral / Delivery Order / IDIQ / etc.) during intake; value is passed
through to `Contract.contract_type` at finalization.
`plan_gross`, `planned_split`, `nist` fields added to draft data schema
and editor form.

### Fixed

Packaging Quote line in GP Summary no longer shows "-$0.00" when
the packaging quote amount is zero — now correctly shows "$0.00".

NSN match now shows a green "matched #N" badge below the NSN field
on CLIN cards, consistent with the existing Supplier badge.

CLIN cards now stay expanded after matching an NSN or Supplier.
Previously the page reload caused all CLINs to collapse.

Supplier match now shows a green "matched #N" badge below the
Supplier field on CLIN cards, matching the existing NSN badge
behaviour.

Packaging card now shows a "Same as supplier — packhouse may not
be needed" warning badge when the packhouse supplier matches any
CLIN's supplier.

Match NSN create panel now pre-fills "Description (optional)" from the
parsed NSN description already stored on the CLIN draft data. Previously
the field was always blank even when the description was available.
Match NSN modal "Parsed value:" box now shows the NSN description
(e.g. ANCHOR,TORSION BAR) on a second line when available, so analysts
can confirm they are matching the correct item without scrolling back
to the CLIN header.

GP calculation corrected: item_value (government contract unit price)
is now multiplied by order_qty before subtracting the supplier quote
total. Previously the formula used item_value as if it were already
a total, producing a wildly incorrect (always negative) planned GP
when item_value was a unit price and order_qty > 1.
Correct formula: planned_gp = (item_value × order_qty) − (unit_price × order_qty + Σ finance_lines.amount).

CLIN ia (Inspection/Acceptance) field now correctly mapped from the
1155 parser result in _clin_to_dict. Previously absent, causing IA
to always be blank after PDF ingest.
Contract-level due_date now derived at ingest as the earliest CLIN
due date. Previously blank on all PDF-ingested drafts.
Sales Class now defaults to 'STATZ' on PDF ingest when that SalesClass
record exists. Previously blank on all ingested drafts.

Removed rendered template comment text that appeared as selectable content
in the Match IDIQ modal results area.
Parent IDIQ match field moved into the Contract Details grid (was a
separate card below Contract Details).

## Inline Create from Match Modal (2026-05-22)
**User-visible changes:**
- The Match modal now has an **+ Add new** panel for Buyer, NSN, and
  Supplier. Click it to inline-create the canonical record and apply it
  to the draft in one step — no need to leave the editor.
- For new Buyers: enter the buyer description. For new NSNs: enter the
  NSN code (and optionally a description). For new Suppliers: enter the
  name and CAGE code (both required).
- The parsed value pre-fills the obvious field (e.g. the parsed buyer
  text → Buyer description) so analysts don't retype.
- Create-and-apply happens inside the same database transaction; if your
  lock has expired or anything else fails, the new canonical row rolls
  back too — nothing is half-created.

**Behind-the-scenes:**
- `matchers.create_record(match_type, payload)` is the single creator.
  Dedup is enforced (Buyer.description, Nsn.nsn_code, Supplier.cage_code).
- `match_endpoint` learned `action: "create"` and `action: "creatable_types"`.
- IDIQ and Contract are intentionally NOT creatable from the modal —
  they have richer required fields. Use the contracts app's full forms
  for those, then re-Match.


## CLIN Editor Overhaul + GP Split (2026-05-21)
**User-visible changes:**
- CLIN rows are now **expandable cards** with clearly separated **Contract Data** and **Supplier/Quote** sections (replaces the wide flat table).
- **Item Type**, **IA**, and **FOB** fields now show full labels (Production, GFAT, Origin, Destination, etc.) instead of single-letter codes. The single-letter code is still stored under the hood.
- **Supplier Due Date** added to each CLIN.
- **Special Payment Terms** dropdown added to each CLIN (sourced from `SpecialPaymentTerms`).
- Finance lines are now entered **per-CLIN** — the shared root-level Finance Lines table has been removed from the editor.
- Each CLIN has a new **GP Split** section: enter company name + percentage; split dollar value is calculated automatically from planned GP.
- New **GP Summary** block shows per-CLIN planned GP, packaging deduction, and net contract GP — all calculated live as you type.
- **Quote Total** auto-calculates as `unit_price × order_qty` per CLIN.

**Behind-the-scenes:**
- Per-CLIN finance lines and splits land in `ContractFinanceLine` and `ClinSplit` rows respectively on finalization.
- Backward-compat: legacy drafts created before this change carry root-level `finance_lines`. Finalization still accepts these and attaches them to the first CLIN, with a warning logged. The legacy path will be removed once the queue is confirmed clear.
- POST key conventions now include nested `clin-<i>-fin-<j>-<field>` and `clin-<i>-split-<j>-<field>` patterns. See `CONTEXT.md`.

### Editor Polish + Field Fixes (2026-05-21)
**User-visible changes:**
- Fixed: parsed 1155 unit price now correctly populates Item Value
  (government contract price), not Quote Price
- CLIN Item Type now defaults to Production when not specified by parser
- Contractor Name and CAGE fields removed from editor (not tracked)
- Sales Class dropdown added to contract header
- PO Number shown as read-only placeholder in contract header
- Packaging section is now hidden by default; click Add Packaging to open
- Packaging section moved above CLINs
- CLIN cards now start collapsed; expand individually as needed
