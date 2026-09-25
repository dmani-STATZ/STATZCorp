# Quotes App — Functional Specification \& Architecture

## Overall Goal

This document defines the functional specification and operational workflow for the Quotes application. The primary purpose of the system is to ingest DIBBS solicitations, match opportunities across supplier capabilities, manage outgoing RFQs and incoming quote responses, assemble DIBBS submission bids (individual and batch), and perform post-award win/loss analytics.

\---

# Phase 1 — Solicitation Ingestion \& Matching

## Step 1 — Ingestion (Automated)

1. Automated daily tasks parse and ingest daily solicitations (`in\\\\\\\*.txt`), approved sources (`as\\\\\\\*.txt`), and batch quote (`bq\\\\\\\*.txt`) templates from DIBBS.
2. **Raw BQ Ingestion**: Each line in `bq\\\\\\\*.txt` is parsed into a 99-element JSON array and stored directly in the `Solicitation\\\\\\\_Line.raw\\\\\\\_bq\\\\\\\_template` field.
3. Initial solicitation state defaults to `Unmatched`.

\---

## Step 2 — Classification \& Multi-Supplier Matching

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

### Manual Matching \& Feedback Loop

Users reviewing the `Unmatched` queue can open an SOL and manually assign suppliers via a modal:

1. **Supplier Search Modal**: User searches supplier directory by name, CAGE, or product type.
2. **Organic Learning Toggles**: Inside the modal, users have explicit checkboxes:

   * `\\\\\\\[x] Save NSN to this Supplier for future runs`
   * `\\\\\\\[x] Save FSC to this Supplier for future runs`
3. Upon selection, the supplier is linked to the SOL, the solicitation state changes to `Matched`, and any selected mappings persist to master NSN/FSC supplier tables.

### User Interface \& Concurrency Handling

* **High-Performance Client-Side Filtering**: The active pool of `Unmatched` solicitations loads into a snappy client-side dataset to allow instant filtering by Set-Aside, Due Date, Estimated Value, etc., using clickable on/off toggle pills without requiring round-trip database reloads.
* **Badges/Pills**: Each row displays visual badges showing match lineages (`\\\\\\\[NSN]`, `\\\\\\\[FSC]`, `\\\\\\\[Manual]`).
* **Multi-User Concurrency**: Active rows display visual indicators when another team member is reviewing them. Saving a match persists asynchronously, transitioning the SOL to `Matched` and updating peer browser sessions without a full page refresh.

\---

## Step 3 — RFQ Dispatch

### RFQ Queue \& Consolidated Batching

* Once matching is reviewed, the user triggers RFQ dispatch.
* **Consolidation**: Outgoing emails are grouped **one email per supplier**.
* A single email to Supplier X contains an itemized table/list of every SOL matched to Supplier X in that cycle:

  * SOL Number
  * NSN Number \& Description
  * Part Number (if available)
  * Quantity \& Unit of Measure
  * SOL Due Date
  * Additional technical/packaging requirements
  * SOL source documents attached
* **Dispatch State**: Upon transmission from the shared `quotes@` account, the solicitation transitions to `RFQ Sent`, clearing it from the active matching queue.

### Archival Policy

* Solicitations that remain in `Unmatched` status for more than **7 calendar days** automatically transition to `Archived` to keep active queues lean.

\---

# Phase 2 — The Quoting Process \& Slide-Out Tray

## Shared Mailbox \& SOL Identification

* Direct integration with the shared `quotes@` inbox.
* Outgoing RFQs include the SOL number in both the **Subject line** and the **Message body** for automated thread detection.
* **Contextual Search Fallback**: If a supplier strips original headers, users have a dedicated search pane within the mailbox view to locate the SOL by NSN, Supplier, or Part Number.

## Data Storage Architecture: Hybrid Relational + Document Model

1. **Relational BQ Lines Table (`Supplier\\\\\\\_Quotes`)**:

   * Contains strictly typed database fields mapped to DIBBS BQ upload specifications:

     * `Supplier\\\\\\\_Unit\\\\\\\_Cost`
     * `Packaging\\\\\\\_Adder\\\\\\\_Unit` (calculated from unit or total)
     * `Packaging\\\\\\\_Vendor\\\\\\\_ID` (links to chosen Packhouse company record)
     * `Freight\\\\\\\_Adder\\\\\\\_Unit` (calculated from unit or total)
     * `Payment\\\\\\\_Terms` (Quote-specific vs Default profile terms with diff indicator)
     * `Lead\\\\\\\_Time\\\\\\\_Days` / Delivery ARO
     * `Min\\\\\\\_Order\\\\\\\_Qty`
     * `Markup\\\\\\\_Type` (`Percentage` or `Fixed\\\\\\\_Price`)
     * `Markup\\\\\\\_Value`
     * `Final\\\\\\\_Government\\\\\\\_Unit\\\\\\\_Price`
     * `Offered\\\\\\\_Part\\\\\\\_Number` \& `Offered\\\\\\\_CAGE`
     * `Is\\\\\\\_Selected\\\\\\\_For\\\\\\\_Bid` (Boolean flag marking the chosen quote for DIBBS submission)
2. **Email Storage \& Many-to-Many Linking**:

   * Raw inbound email bodies, headers, sender data, and attachment references are stored in an email repository (with full raw payload preserved in `JSON`).
   * A junction table (`SOL\\\\\\\_Email\\\\\\\_Link`) binds emails to solicitations:

     * **One email can link to multiple SOLs** (e.g., vendor responds to a consolidated RFQ with prices for multiple parts in one reply).
     * **One SOL can link to multiple emails** (e.g., initial quotes, price revisions, term clarifications).
   * Inside the quote entry screen, users can click a link to pull up the exact source email and attachments from which the quote numbers were transcribed.
3. **NSN Logistics Knowledge Base (`NSN\\\\\\\_Logistics\\\\\\\_Catalog`)**:

   * Internal learning datastore for part physical specifications:

     * `NSN` (Primary Key / indexed)
     * `Weight\\\\\\\_Lbs`
     * `Length\\\\\\\_Inches`, `Width\\\\\\\_Inches`, `Height\\\\\\\_Inches`
     * `Source\\\\\\\_Notes`
     * `Date\\\\\\\_Last\\\\\\\_Verified`

## Quote Entry \& Slide-Out Tray (Option B Flow)

### Split / Combine CLIN Management

* **Default Mode (Combined / Linked)**: Pricing, lead time, packaging, and freight apply across all CLINs on the solicitation automatically.
* **Split Mode (`\\\\\\\[ Split CLINs ]`)**: Unlinks CLINs, allowing independent cost entry for:

  * Destination-specific freight variations.
  * Staggered delivery days per delivery depot.
  * Dedicated First Article Testing (FAT) / Production Lot Testing (PLT) line items (`0001S00000052`).

### Specialty Sub-Modals

#### 1\. Third-Party Packaging Sub-Modal

* **Packhouse Directory**: Assigns third-party packhouse or sets "Included by Part Supplier".
* **Two-Way Calculation**:
$$\\text{Unit Pack Cost} = \\frac{\\text{Total Pack Cost}}{\\text{Quantity}}$$
* **Supplier Persistence**: Toggle `\\\\\\\[x] Supplier always requires external packaging` updates master vendor profile.

#### 2\. Freight \& Logistics Sub-Modal

* **Organic Dimensions Datastore**: Pre-populates historical dims from `NSN\\\\\\\_Logistics\\\\\\\_Catalog`. Checking `\\\\\\\[x] Save/Update dimensions` updates internal NSN specs.
* **Two-Way Calculation**:
$$\\text{Unit Freight Cost} = \\frac{\\text{Total Freight Cost}}{\\text{Quantity}}$$

### Tip-Screen Margin Selector

* **Preset Buttons**: Quick margin pills (`\\\\\\\[ 2% ]`, `\\\\\\\[ 4% ]`, `\\\\\\\[ 6% ]`).
* **Custom Entry**: Direct percentage input or direct final selling price target (back-calculating effective margin automatically).

\---

# Phase 3 — Bid Staging, DIBBS Validations \& JSON-Based Batch Export

## Bid Staging \& Multi-Quote Comparison

* **Automated Lowest-Quote Default**: Automatically marks the lowest landed cost quote as `Is\\\\\\\_Selected\\\\\\\_For\\\\\\\_Bid`, flagged with a visual selection icon.
* **Side-by-Side Comparison Modal ("Vehicle Comparison")**: Compares base supplier costs, third-party packhouse rates, freight adders, total landed costs, delivery days vs. SOL maximums, and payment terms (Net 15 vs. Net 30) side-by-side with a one-click manual selection button.

\---

## DIBBS Batch Quote Generation Engine (JSON Array In-Place Mutation)

### Ingestion \& Export Architecture

1. **At Import (Step 1)**: Each line of `bq\\\\\\\*.txt` is parsed into a Python `list` / JSON array of exactly 99 strings and saved to `Solicitation\\\\\\\_Line.raw\\\\\\\_bq\\\\\\\_template`.
2. **At Export (Phase 3)**: The export generator pulls the raw JSON array and updates only the quoter indices using the winning quote record:

```python
# Array index mapping for the 99 physical CSV fields in DIBBS bq\\\\\\\*.txt
bq\\\\\\\[5]  = QUOTER\\\\\\\_CAGE                         # Col 006: Quoter CAGE
bq\\\\\\\[6]  = QUOTER\\\\\\\_CAGE                         # Col 007: Quote For CAGE
bq\\\\\\\[7]  = "B"                                 # Col 013: Small Business Rep ('B' or 'M')
bq\\\\\\\[8]  = "JN"                                # Col 018: Joint Venture ('JN' = No)
bq\\\\\\\[10] = "Y6"                                # Col 021: Affirmative Action Compliance
bq\\\\\\\[11] = "Y4"                                # Col 022: Previous Contracts Compliance
bq\\\\\\\[12] = "A"                                 # Col 023: Alternate Disputes Resolution
bq\\\\\\\[13] = "BI" if is\\\\\\\_compliant else "BW"      # Col 024: Bid Type (BI, BW, AB)
bq\\\\\\\[14] = "1"                                 # Col 025: Discount Terms (1 = Net 30)
bq\\\\\\\[15] = f"QT-{quote.id}"                    # Col 026: Vendor Quote Number
bq\\\\\\\[16] = "90"                                # Col 027: Days Quote Valid
bq\\\\\\\[17] = "Y" if quote.packaging\\\\\\\_ok else "N"  # Col 028: Meets Packaging Requirement
bq\\\\\\\[18] = "NAP"                               # Col 029: BOA/FSS/BPA Indicator
bq\\\\\\\[32] = f"{quote.gov\\\\\\\_unit\\\\\\\_price:.5f}"       # Col 050: Quoted Unit Price
bq\\\\\\\[33] = str(quote.delivery\\\\\\\_days\\\\\\\_aro)        # Col 051: Quoted Delivery Days ARO
bq\\\\\\\[83] = quote.part\\\\\\\_number\\\\\\\_offered\\\\\\\_code      # Col 106: Part Number Offered Code (1=Exact)
bq\\\\\\\[84] = quote.offered\\\\\\\_cage                  # Col 107: Manufacturer CAGE
bq\\\\\\\[85] = quote.offered\\\\\\\_part\\\\\\\_number           # Col 108: Manufacturer Part Number
bq\\\\\\\[98] = ""                                  # Col 121: Quote Remarks (Must be "" for T/U solicitations)



