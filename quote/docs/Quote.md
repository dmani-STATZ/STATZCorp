# Quotes App — Functional Specification & Architecture

## Overall Goal
This document defines the functional specification and operational workflow for the Quotes application. The primary purpose of the system is to ingest DIBBS solicitations, match opportunities across supplier capabilities, manage outgoing RFQs and incoming quote responses, assemble DIBBS submission bids (individual and batch), and perform post-award win/loss analytics.

---

# Phase 1 — Solicitation Ingestion & Matching

## Step 1 — Ingestion (Automated)
1. Automated daily tasks parse and ingest daily solicitations (`in*.txt`), approved sources (`as*.txt`), and batch quote (`bq*.txt`) templates from DIBBS.
2. Records are loaded into the primary solicitation datastore.
3. Initial solicitation state defaults to `Unmatched`.

---

## Step 2 — Classification & Multi-Supplier Matching

### Core State Model
To prevent status collisions and simplify multi-user workflows, solicitations exist in two primary operational lifecycle states during this phase:
* **`Unmatched`**: Solicitation has zero linked suppliers.
* **`Matched`**: Solicitation has at least one linked supplier (whether via NSN, FSC, or manual assignment).

Match lineage is preserved as metadata on the relationship:
* **Match Source**: `NSN`, `FSC`, `Manual`
* **Match Target**: Supplier ID + Contact details

### Matching Logic (All Possibilities)
* Matching is **additive**: If an SOL matches 2 suppliers via NSN, 1 supplier via FSC, and a user manually tags another, **all 4 suppliers are linked** to the solicitation.
* **NSN ↔ Supplier Mapping**: Many-to-many relationship.
* **FSC ↔ Supplier Mapping**: Many-to-many relationship.
* **Re-running Matching**: Users can update matching tables and trigger re-classification at any time without clearing existing manual matches.

### Manual Matching & Feedback Loop
Users reviewing the `Unmatched` queue can open an SOL and manually assign suppliers via a modal:
1. **Supplier Search Modal**: User searches supplier directory by name, CAGE, or product type.
2. **Organic Learning Toggles**: Inside the modal, users have explicit checkboxes:
   * `[x] Save NSN to this Supplier for future runs`
   * `[x] Save FSC to this Supplier for future runs`
3. Upon selection, the supplier is linked to the SOL, the solicitation state changes to `Matched`, and any selected mappings persist to master NSN/FSC supplier tables.

### User Interface & Concurrency Handling
* **High-Performance Client-Side Filtering**: The active pool of `Unmatched` solicitations loads into a snappy client-side dataset to allow instant filtering by Set-Aside, Due Date, Estimated Value, etc., using clickable on/off toggle pills without requiring round-trip database reloads.
* **Badges/Pills**: Each row displays visual badges showing match lineages (`[NSN]`, `[FSC]`, `[Manual]`).
* **Multi-User Concurrency**: Active rows display visual indicators when another team member is reviewing them. Saving a match persists asynchronously, transitioning the SOL to `Matched` and updating peer browser sessions without a full page refresh.

---

## Step 3 — RFQ Dispatch

### RFQ Queue & Consolidated Batching
* Once matching is reviewed, the user triggers RFQ dispatch.
* **Consolidation**: Outgoing emails are grouped **one email per supplier**.
* A single email to Supplier X contains an itemized table/list of every SOL matched to Supplier X in that cycle:
  * SOL Number
  * NSN Number & Description
  * Part Number (if available)
  * Quantity & Unit of Measure
  * SOL Due Date
  * Additional technical/packaging requirements
  * SOL source documents attached
* **Dispatch State**: Upon transmission from the shared `quotes@` account, the solicitation transitions to `RFQ Sent`, clearing it from the active matching queue.

### Archival Policy
* Solicitations that remain in `Unmatched` status for more than **7 calendar days** automatically transition to `Archived` to keep active queues lean.

---

# Phase 2 — The Quoting Process & Slide-Out Tray

## Shared Mailbox & SOL Identification
* Direct integration with the shared `quotes@` inbox.
* Outgoing RFQs include the SOL number in both the **Subject line** and the **Message body** for automated thread detection.
* **Contextual Search Fallback**: If a supplier strips original headers, users have a dedicated search pane within the mailbox view to locate the SOL by NSN, Supplier, or Part Number.

## Data Storage Architecture: Hybrid Relational + Document Model
1. **Relational BQ Lines Table (`Supplier_Quotes`)**:
   * Contains strictly typed database fields mapped to DIBBS BQ upload specifications:
     * `Supplier_Unit_Cost`
     * `Packaging_Adder_Unit` (calculated from unit or total)
     * `Packaging_Vendor_ID` (links to chosen Packhouse company record)
     * `Freight_Adder_Unit` (calculated from unit or total)
     * `Payment_Terms` (Quote-specific vs Default profile terms with diff indicator)
     * `Lead_Time_Days` / Delivery ARO
     * `Min_Order_Qty`
     * `Markup_Type` (`Percentage` or `Fixed_Price`)
     * `Markup_Value`
     * `Final_Government_Unit_Price`
     * `Offered_Part_Number` & `Offered_CAGE`
     * `Is_Selected_For_Bid` (Boolean flag marking the chosen quote for DIBBS submission)
2. **Email Storage & Many-to-Many Linking**:
   * Raw inbound email bodies, headers, sender data, and attachment references are stored in an email repository (with full raw payload preserved in `JSON`).
   * A junction table (`SOL_Email_Link`) binds emails to solicitations:
     * **One email can link to multiple SOLs** (e.g., vendor responds to a consolidated RFQ with prices for multiple parts in one reply).
     * **One SOL can link to multiple emails** (e.g., initial quotes, price revisions, term clarifications).
   * Inside the quote entry screen, users can click a link to pull up the exact source email and attachments from which the quote numbers were transcribed.
3. **NSN Logistics Knowledge Base (`NSN_Logistics_Catalog`)**:
   * Serves as an internal learning datastore for part physical specifications:
     * `NSN` (Primary Key / indexed)
     * `Weight_Lbs`
     * `Length_Inches`, `Width_Inches`, `Height_Inches`
     * `Source_Notes` (e.g., "Sourced from vendor spec sheet", "Estimated from prior drawing")
     * `Date_Last_Verified`

## Quote Entry & Slide-Out Tray (Option B Flow)

### Split / Combine CLIN Management
Solicitations frequently contain multiple line items (e.g., multiple destinations, staggered delivery schedules, or dedicated First Article Testing lines):
* **Default Mode (Combined / Linked)**: Pricing, lead time, packaging, and freight apply across all CLINs on the solicitation automatically.
* **Split Mode (`[ Split CLINs ]`)**: Unlinks CLINs, allowing independent cost entry for:
  * Destination-specific freight variations.
  * Staggered delivery days per delivery depot.
  * Dedicated First Article Testing (FAT) / Production Lot Testing (PLT) line items (pricing vs. waiver requests).

### Specialty Sub-Modals

#### 1. Third-Party Packaging Sub-Modal
* **Packhouse Directory**: Assigns third-party packhouse or sets "Included by Part Supplier".
* **Two-Way Calculation**:
  $$\text{Unit Pack Cost} = \frac{\text{Total Pack Cost}}{\text{Quantity}}$$
* **Supplier Persistence**: Toggle `[x] Supplier always requires external packaging` updates master vendor profile.

#### 2. Freight & Logistics Sub-Modal
* **Organic Dimensions Datastore**: Pre-populates historical dims from `NSN_Logistics_Catalog`. Checking `[x] Save/Update dimensions` updates internal NSN specs.
* **Two-Way Calculation**:
  $$\text{Unit Freight Cost} = \frac{\text{Total Freight Cost}}{\text{Quantity}}$$

### Tip-Screen Margin Selector
* **Preset Buttons**: Quick margin pills (`[ 2% ]`, `[ 4% ]`, `[ 6% ]`).
* **Custom Entry**: Direct percentage input or direct final selling price target (back-calculating effective margin automatically).

---

# Phase 3 — Bid Staging, DIBBS Validations & Batch File Generation

## Bid Staging & Multi-Quote Comparison

### Automated Lowest-Quote Selection & Visual Indicator
* The system automatically defaults the lowest landed cost quote as `Is_Selected_For_Bid`.
* Displays a distinct **Tally Badge & Selection Icon** (e.g., `[ 3 Quotes (Auto: Lowest) ]`) alerting users that an automated choice was made.

### Side-by-Side Quote Comparison View ("Vehicle Comparison")
Clicking `[ Compare Quotes ]` opens an evaluation drawer displaying competing vendor bids side-by-side:
* Base Part Cost vs. Landed Unit Cost (inclusive of packhouse and freight adders).
* Delivery Lead Time ARO vs. Maximum Allowed Delivery Days.
* Cash Flow Evaluation: Payment terms comparison (e.g., Net 15 vs. Net 30).
* `[ Select This Bid ]`: One-click override of the automated default.

---

## DIBBS Batch Quote Generation Engine

### Template Preservation Principle
The daily downloaded `bq*.txt` file from DIBBS is used as the base template. The engine parses the existing template, updates only the designated quoter positions, preserves untouched non-bid lines, and writes the output back in standard `ISO-8859-1` comma-delimited format with quotes.

### Primary DIBBS Column Specification (121-Field Layout)

| Field # | Level | Field Name | Type / Length | STATZ System Source / Logic |
| :--- | :--- | :--- | :--- | :--- |
| **001** | Header | Solicitation Number | Char(13) | RFQ Requirement (from DIBBS) |
| **002** | Header | Solicitation Type Indicator | Char(1) | RFQ Requirement (`F`=Fast Auto, `I`=AIDC, `P`=Auto) |
| **003** | Header | Small Business Set Aside | Char(1) | RFQ Requirement (`Y`, `H`, `R`, `L`, `A`, `E`, `N`) |
| **004** | Header | Additional Clause Fill-Ins | Char(1) | RFQ Requirement (`N`, `Y`) |
| **005** | Header | Return By Date | Char(10) | RFQ Requirement (`MM/DD/YYYY`) |
| **006** | Header | Quoter CAGE Code | Char(5) | STATZ CAGE Code |
| **007** | Header | Quote For CAGE Code | Char(5) | Target CAGE (Matches Quoter CAGE) |
| **013** | Header | Small Business Representation | Char(1) | `B` (Small Business) or `M` (Small Disadv Business) |
| **018** | Header | Joint Venture | Char(2) | `JN` (Not a Joint Venture) or `JV` |
| **021** | Header | Affirmative Action Compliance | Char(2) | `Y6` (Developed/on file) or `NA` |
| **022** | Header | Previous Contracts Compliance | Char(2) | `Y4` (Participated/Filed) or `NA` |
| **023** | Header | Alternate Disputes Resolution | Char(1) | `A` (Agree to use ADR) |
| **024** | Header | Bid Type Code | Char(2) | `BI` (Without Exception), `BW` (With Exception), `AB` (Alternate Bid), `DQ` (No Bid) |
| **025** | Header | Discount Terms Code | Char(2) | `1` (Net 30) or prompt payment discount codes |
| **026** | Header | Vendor Quote Number | Char(15) | STATZ Internal Quote Reference ID |
| **027** | Header | Days Quote Valid | Num(3) | Defaults to `90` (Mandatory) |
| **028** | Header | Meets Packaging Requirement | Char(1) | `Y` (Yes) or `N` (Forces `BW`/`AB`) |
| **029** | Header | BOA / FSS / BPA Indicator | Char(3) | Defaults to `NAP` (Not Applicable) |
| **032** | Header | FOB Point | Char(1) | `D` (Destination) or `O` (Origin - requires city/state/country) |
| **036** | Header | Inspection Point Code | Char(1) | `D` (Destination) or `O` (Origin - requires inspection CAGE) |
| **044** | Line | Solicitation Line Number | Char(4) | RFQ Requirement (`0001`, `0002`, etc.) |
| **046** | Line | Purchase Request Number | Char(10) | RFQ Requirement (PR number from DIBBS) |
| **047** | Line | National Stock Number | Char(45) | RFQ Requirement (NSN from DIBBS) |
| **048** | Line | Unit of Issue | Char(2) | RFQ Requirement (`EA`, `PG`, `KT`, etc.) |
| **049** | Line | Quantity | Num(10) | RFQ Requirement (Must match unless exception taken) |
| **050** | Line | Unit Price | Num(13,5) | **Calculated Government Unit Sell Price** (Mandatory, e.g. `34.45000`) |
| **051** | Line | Delivery Days | Num(4) | **Quoted Delivery Days ARO** (Whole numbers only, e.g. `45`) |
| **057** | Header | HUBZone Preference Indicator | Char(1) | RFQ Requirement (`Y` or `N`) |
| **058** | Header | Waiver of HUBZone Preference | Char(1) | `N` or `A` (Not Applicable) |
| **062** | Product | Trade Agreements Indicator | Char(1) | RFQ Requirement (`N`, `Y`, `I`) |
| **064** | Line | First Article Waiver Code | Char(1) | `Y` (Request Waiver) or `N` (Required if FAT CLIN `0001S00000052`) |
| **065** | Product | Hazardous Material ID | Char(1) | `N` (No) or `Y` (Yes) |
| **067** | Product | Material Requirements | Char(1) | `0` (New/Standard supplies) |
| **068** | Product | Buy American Indicator | Char(1) | RFQ Requirement (`N`, `Y`, `I`) |
| **069** | Product | Free Trade Agreements Indicator| Char(1) | RFQ Requirement (`N`, `Y`, `A`, `B`, `I`) |
| **070** | Product | Buy American / FTA End Product | Char(2) | `D` (Domestic), `Q` (Qualifying), `NQ` (Non-Qualifying) |
| **096** | Product | Quantity Variance Plus | Num(2) | Defaults to `0` (Range 0–10) |
| **097** | Product | Quantity Variance Minus | Num(2) | Defaults to `0` (Range 0–10) |
| **098** | Product | Minimum Order Qty Code | Char(1) | Defaults to `N` (No) |
| **100** | Product | Immediate Shipment Available | Char(1) | Defaults to `N` (No) |
| **102** | Product | Manufacturer / Dealer | Char(2) | `DD` (Dealer) or `MM` (Manufacturer) |
| **103** | Product | Actual Manufacturing CAGE | Char(5) | CAGE code of producing supplier/factory (Required if Dealer) |
| **105** | Product | Item Description Indicator | Char(1) | RFQ Requirement (`P`=Approved Source, `D`=Drawing, `B`=Source Control) |
| **106** | Product | Part Number Offered Code | Char(1) | `1` (Exact Product), `2` (Alternate Product - forces `AB`), `3`-`5` (Superseding/Previous) |
| **107** | Product | Part Number Offered CAGE | Char(5) | Approved CAGE from `as*.txt` file |
| **108** | Product | Part Number Offered - Part No | Char(40) | Approved Part Number from `as*.txt` file |
| **117** | Product | Higher-Level Quality Indicator| Char(1) | RFQ Requirement (`N`, `8`=AS9100, `7`=ISO9001, `6`=AS9003) |
| **118** | Product | Higher-Level Quality Code | Char(1) | Quality standard held by producing facility (`7`, `8`, etc.) |
| **120** | Product | Child Labor Certification Code | Char(1) | Defaults to `N` (No - mandatory compliance) |
| **121** | Header | Quote Remarks | Char(255) | **Must remain blank** on automated "T" or "U" solicitations to preserve auto-award eligibility |

### Pre-Flight Automated Syntax Validations
Prior to file export, the application validates:
1. **Column Cardinality Assertion**: Every output line contains exactly 121 comma-separated delimited strings, matching the field layout above. (Corrected from 99 — the layout in this document and the live `sales/services/bq_export.py` writer are both 121. Confirm with a byte-level diff against a DIBBS-accepted `bq` file before trusting either number.)
2. **Numeric Precision Enforcement**: Col 50 (`Unit Price`) formatted to maximum 5 decimals without leading symbols (`$`).
3. **Integer Enforcement**: Col 51 (`Delivery Days`) contains whole positive integers without decimal points.
4. **Auto-Award Protection**: If character 9 of Solicitation Number is `T` or `U`, Col 121 (`Quote Remarks`) is asserted to be empty string `""` to prevent accidental loss of auto-award status.
5. **Exact Match Assertion**: If Col 106 is set to `1` (Exact Product), asserts that Col 107 (CAGE) and Col 108 (Part #) exist in the daily `as*.txt` master source catalog for that NSN.

---

# Phase 4 — Post-Award Analytics & Intelligence ("Our Bids")

## Executive Dashboard
Positioned above the grid with preset timeframe filters (`This Week`, `This Month`, `This Quarter`, `All Time`):
* **Won vs. Lost Counters**: Total bids submitted, win percentage, and total contract dollar value won vs. lost.
* **"Within 5%" Missed Opportunity Counter**: Highlights bids lost by under 5%, isolating revenue left on the table due to minor pricing differences.
* **Average Margin Won**: Historical average markup on winning bids.

## "Our Bids" Master Grid
A sortable, filterable HTML table populated by nightly award reconciliation:
* **Columns**:
  * **Outcome Badge**: `[WON]` (Green), `[LOST]` (Red), `[PENDING]` (Gray/Blue).
  * **Solicitation Number** & **NSN / Nomenclature**.
  * **Submission Date**.
  * **Our Bid Unit Price** vs. **Winning Award Unit Price**.
  * **Dollar Delta**:
    $$\text{Dollar Delta} = \text{Our Bid Price} - \text{Winning Award Price}$$
  * **Percentage Spread**:
    $$\text{Percentage Spread} = \frac{\text{Our Bid Price} - \text{Winning Award Price}}{\text{Winning Award Price}} \times 100$$
  * **Action**: `[ Details ]` button opening the forensic drawer.

## Slide-Out Bid Forensic Detail Drawer
Clicking `[ Details ]` on any bid row opens a slide-out drawer providing full insight into the transaction:
1. **Winning Award Summary (Nightly Ingestion)**:
   * Contract / PIID Number and Award Date.
   * Winning Entity Name and CAGE Code (resolved via CAGE master directory).
   * Total and Unit Awarded Value.
   * Exact dollar and percentage delta by which STATZ won or lost.
2. **STATZ Frozen Bid Snapshot**:
   * Part Supplier used and quoted unit cost.
   * Packhouse vendor assigned and packaging adder.
   * Freight adder applied and physical dimensions recorded.
   * Internal markup applied and final government unit price submitted.
   * Internal sales rep who submitted the quote and direct link to source email thread.
3. **Competitive Pattern Intelligence**:
   * Tracks competitor win frequency across the same FSC / NSN.
   * Identifies suppliers whose pricing regularly proves non-competitive against winning market rates.