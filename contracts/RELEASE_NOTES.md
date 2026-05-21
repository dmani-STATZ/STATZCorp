# Contracts Release Notes

## [Unreleased]

### Added

- **[2026-05-21] Finance Audit — Log Split Paid** — Jenny can now record split paid amounts directly from the Finance Audit page. Click the "Split Paid" header in the Split Summary card to open the Log Split Paid modal. Enter the total paid for each company and save — the system distributes the amount proportionally across CLINs automatically. A warning highlights any discrepancy between what was paid and the expected split value.

### Fixed

- **[2026-05-21] Bug Fix — Add Split button on CLIN detail page** — The "Add Split" button on the CLIN detail page was not responding to clicks. This has been fixed.

### Changed

- **[2026-05-21] CLIN Detail — Added "Finance Audit" link to the sidebar** — Direct navigation back to the Finance Audit page for the parent contract, removing the need to go through the contract management page.

- **[2026-05-21] Finance Audit — CLIN Item # links to detail page** — CLIN Item # in the Finance Audit CLINs table is now a link to the CLIN detail page, giving users direct access to edit split values and other CLIN-level data without leaving the finance workflow.

- Acknowledgment section on Contract Management renamed from "CLIN Acknowledgment" to "Acknowledgment" and promoted to contract-level. One toggle now fires across all CLINs on the contract.

### Added

- **PO Snippet Library** — Contract managers can now store, organize, and copy reusable PO paragraph snippets from the Options menu on any contract management page. Snippets are company-scoped, grouped by category, and searchable. Full add / edit / delete support with one-click clipboard copy.

On PO Sent to Supplier toggle:

- "PO ACKNOWLEDGMENT LETTER Followup" note and 10-day reminder created on the first Production CLIN.
- "FIRST SUPPLIER CHECK IN" note and reminder (supplier_due_date − 60 days) created for the first Production CLIN of each unique supplier due date, and for every non-Production CLIN.
- CLINs with no supplier_due_date receive a note only with a clear message that no reminder was created.
