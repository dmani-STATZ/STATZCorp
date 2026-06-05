---
id: 2026-06-05-intake-editor-improvements
title: Intake — Editor layout and GP split improvements
published: true
publish_date: 2026-06-05
tags: [improved, contracts]
critical: false
---

Several improvements to the intake draft editor layout and GP split behavior:

**Layout:**
- Contract Details form reordered to a 2-column layout: Contract Number / IDIQ Contract, PO / PR Number, Buyer / Sales Class, Contract Type / Solicitation Type, Award Date / Due Date, Contract Value, Plan Gross / Planned Split, Files URL / NIST.
- CLIN card Contract Data section reordered: Item Number, Item Type, CLIN PO Number (display-only), IA on top row; FOB full-width; NSN + Due Date; Quantity / UOM / Unit Price / Total Value.
- Both "INTAKE TYPE" (parser-set, read-only) and "CONTRACT TYPE" (analyst-selected canonical type) are now visible in the Contract Details section.
- Finance Lines and GP Split entries now render as individual cards instead of table rows.

**GP Split smart defaults:**
- Planned Split auto-populates as a plain percentage total (e.g. "100") derived from the sum of all CLIN split row percentages.
- Clicking **+ Add Split** on a CLIN with no splits pre-fills the first entry as STATZ at 100%.
- Adding a second split automatically drops the first to 50%, leaving the new entry blank for the analyst to fill in.
- Adding a third or more splits makes no automatic adjustments.

**Fields added to draft schema:** `canonical_contract_type_id`, `plan_gross`, `planned_split`, `nist`.
