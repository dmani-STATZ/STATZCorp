# Contracts Release Notes

## [Unreleased]

### Added

- **[2026-05-27] Add CLIN — "Copy From" defaults.** When adding a new CLIN to a contract that already has CLINs, a "Copy from existing CLIN" dropdown appears at the top of the form. Selecting a source CLIN automatically populates Supplier, NSN, I&A, FOB, UOM, Unit Price, Price Per Unit, Payment Terms, PO #, Tab #, and Due Dates — no manual matching required. Item Number, Quantity, and financial totals are intentionally left blank for the new CLIN. Entering a Quantity now also auto-calculates Total Value and Quote Total without needing to click ReCalc. Match buttons on the NSN and Supplier fields now turn green with a checkmark once a value is selected (whether via the picker or copy-from), and revert to blue if cleared. CLIN PO Number is now also copied when using Copy From.

- **[2026-05-27] Document Browser Improvements** — Files and folders can now be selected using checkboxes. A new **Actions** dropdown menu replaces the Save Path button — all document browser actions live in one place. **Save Path** — same behavior as before. **Open in SharePoint** — opens the current folder in SharePoint; if a folder row is selected, opens that folder instead. **Download** — appears when files are selected; downloads files directly to your computer. **Delete** — appears for staff users when files are selected; permanently removes files from SharePoint after confirmation.

- **[2026-05-21] Finance Audit — Log Split Paid** — Jenny can now record split paid amounts directly from the Finance Audit page. Click the "Split Paid" header in the Split Summary card to open the Log Split Paid modal. Enter the total paid for each company and save — the system distributes the amount proportionally across CLINs automatically. A warning highlights any discrepancy between what was paid and the expected split value.

### Fixed

- **[2026-06-01] Bug Fix — CLIN Fix partial shipment Quote/Item Value not persisting on re-render.** Manually entered Quote Value and Item Value on partial shipment conversions now persist correctly when interacting with the parent CLIN dropdown or switching between rows.

- **[2026-05-21] Bug Fix — Add Split button on CLIN detail page** — The "Add Split" button on the CLIN detail page was not responding to clicks. This has been fixed.

### Changed

- Processing contract form: Packhouse and Contract Charges are now independent 
  side-by-side sections (50/50 layout). Each section has its own collapsed/expanded 
  toggle. Removed "+ Add Contract Charge" button from the Contract Actions sidebar.

- **[2026-05-27] Contract Management — CLIN card Ship Qty now read-only on converted CLINs.** The Ship Qty field on the contract management CLIN detail card is now shown as a read-only value (not an edit button) when the CLIN has shipments, matching the same rule on the CLIN detail page. Ship Qty is always the sum of individual shipment quantities on converted CLINs.

- **[2026-05-27] CLIN Detail — Shipment and value displays stay in sync.** Ship Qty on the CLIN detail page now updates automatically after any shipment is added, edited, or deleted — no page reload needed. On CLINs with shipments, Ship Qty is shown as a read-only rollup (∑) since it is always the sum of individual shipment quantities. Total Value and Quote Total also refresh immediately when Order Qty, Unit Price, or Price Per Unit are changed.

- **[2026-05-27] CLIN Detail — Quantity and price changes now update totals automatically.** Changing Order Qty, Unit Price, or Price Per Unit on a CLIN now immediately updates the Total Value and Quote Total fields on the page — no page reload needed. The values are also saved to the database and fully audited in the change history. Ship Qty is now shown as a read-only rollup on CLINs that have shipments, reflecting the sum of all individual shipment quantities.

- **[2026-05-27] Finance Audit — one workbench on the CLIN table.** The top **Add Shipment**, **Add Finance Line**, and **Log Payment** buttons are gone. Every CLIN has **+ Shipment** and **+ cost** on its row; each shipment has **+ cost** for trucking and other unplanned costs. Supplier and customer payments are logged by clicking **Paid** or **Customer Pay** on the shipment — you can now **edit** a mistyped amount in the ledger instead of deleting and re-entering. CLIN **Paid** and **Customer Pay** are always read-only; add a shipment first, then record money there. The Payment Activity panel is a read-only history.

- **[2026-05-27] Finance Audit — Paid & Customer Pay roll up from shipments.** For CLINs that have shipments (marked with the blue "S"), Paid and Customer Pay are now calculated automatically from the shipments and are no longer edited directly on the CLIN — record those amounts on the shipment instead. CLINs that haven't been converted to shipments yet keep working exactly as before. This removes a behind-the-scenes duplication that could cause totals to drift.

- **[2026-05-27] Finance Audit — shipment values now calculate automatically.** A shipment's Quote Value and Item Value are now calculated from its quantity × the CLIN's unit price, instead of being typed in by hand. To change them, change the shipment's quantity. For older contracts missing a unit price, a small "set unit price" option appears on those CLINs so the values can still be calculated correctly.

- **[2026-05-26] Finance Audit — Plan Gross is now direct-edit.** Plan Gross on the Finance Audit page is now edited by clicking the value and typing the number directly, instead of logging a payment-history entry — matching how Item Value and Quote Value now work. Every change is fully recorded in the field's history.

- **[2026-05-26] Finance Audit — Item Value & Quote Value are now direct-edit.** Item Value and Quote Value on the Finance Audit page (and CLIN detail) are now edited by clicking the value and typing the number directly, instead of logging a payment-history entry. Type what the CLIN is worth and the system fills in the per-unit price behind the scenes. Every change is still fully recorded in the field's history. (Paid and Customer Pay are unchanged for now.)

- **[2026-05-21] CLIN Detail — Added "Finance Audit" link to the sidebar** — Direct navigation back to the Finance Audit page for the parent contract, removing the need to go through the contract management page.

- **[2026-05-21] Finance Audit — CLIN Item # links to detail page** — CLIN Item # in the Finance Audit CLINs table is now a link to the CLIN detail page, giving users direct access to edit split values and other CLIN-level data without leaving the finance workflow.

- Acknowledgment section on Contract Management renamed from "CLIN Acknowledgment" to "Acknowledgment" and promoted to contract-level. One toggle now fires across all CLINs on the contract.

### Added

- **PO Snippet Library** — Contract managers can now store, organize, and copy reusable PO paragraph snippets from the Options menu on any contract management page. Snippets are company-scoped, grouped by category, and searchable. Full add / edit / delete support with one-click clipboard copy.

On PO Sent to Supplier toggle:

- "PO ACKNOWLEDGMENT LETTER Followup" note and 10-day reminder created on the first Production CLIN.
- "FIRST SUPPLIER CHECK IN" note and reminder (supplier_due_date − 60 days) created for the first Production CLIN of each unique supplier due date, and for every non-Production CLIN.
- CLINs with no supplier_due_date receive a note only with a clear message that no reminder was created.
