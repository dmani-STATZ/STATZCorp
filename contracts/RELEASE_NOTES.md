# Contracts Release Notes

## [Unreleased]

### Changed

- Acknowledgment section on Contract Management renamed from "CLIN Acknowledgment" to "Acknowledgment" and promoted to contract-level. One toggle now fires across all CLINs on the contract.

### Added

On PO Sent to Supplier toggle:

- "PO ACKNOWLEDGMENT LETTER Followup" note and 10-day reminder created on the first Production CLIN.
- "FIRST SUPPLIER CHECK IN" note and reminder (supplier_due_date − 60 days) created for the first Production CLIN of each unique supplier due date, and for every non-Production CLIN.
- CLINs with no supplier_due_date receive a note only with a clear message that no reminder was created.
