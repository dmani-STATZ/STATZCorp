# Contracts Release Notes

## [Unreleased]

### Added

- **[2026-05-21] Finance Audit — Log Split Paid** — Jenny can now record split paid amounts directly from the Finance Audit page. Click the "Split Paid" header in the Split Summary card to open the Log Split Paid modal. Enter the total paid for each company and save — the system distributes the amount proportionally across CLINs automatically. A warning highlights any discrepancy between what was paid and the expected split value.

### Fixed

- **[2026-05-21] Bug Fix — Add Split button on CLIN detail page** — The "Add Split" button on the CLIN detail page was not responding to clicks. This has been fixed.

### Changed

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
