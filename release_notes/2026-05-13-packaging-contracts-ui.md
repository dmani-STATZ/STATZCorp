---
id: 2026-05-13-packaging-contracts-ui
title: Packaging Information — Contracts UI
published: false
publish_date: 2026-05-13
tags: [new, contracts]
critical: false
---

## Packaging Information — Contracts UI

Contract packaging details (packhouse, quote, payment tracking) are now visible and editable throughout the Contracts app.

### Contract Management
- A **Packhouse** line now appears below the Contract Line Items table showing the assigned packhouse supplier and cage code.
- Tapping the ⓘ icon opens a detail modal with full packaging info. Notes can be edited directly from this modal.

### Contract Review
- A new **Packaging** section card appears between Misc and Split Summary.
- Packhouse and notes are editable here. Financial fields (quote, paid, invoice) show read-only values with a prompt to edit on Finance Audit.

### Finance Audit
- The middle summary column now shows a **Packaging** card below the Split Summary. The card face shows packhouse name, cage, and a quick Q/Pd summary. Tap **Details →** to open a modal with full editing access.
- Quote and paid amounts open the Payment History popup for a full audit trail of changes.
- Invoice # and Payment Date are editable inside the Details modal.
- The Contract Summary card now shows **Packaging Cost** as a named red deduction alongside Finance Costs.
- **Adj Gross** now deducts packaging cost using the formula: `Plan Gross − COALESCE(Paid, Quote) − Finance Costs`.
