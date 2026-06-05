---
id: 2026-06-01-intake-contract-level-charges
title: Intake — Contract Level Charges
published: true
publish_date: 2026-06-01
tags: [new, contracts]
critical: false
---

A new **Contract Level Charges** section is available in the AWD/PO/DO/INTERNAL draft editor, positioned between Packaging and the CLIN stack.

Analysts can add one or more named charges (e.g. GSI Fee, Estimated Freight) with an estimated dollar amount using the **+ Add Line** button. The section is hidden by default — click **+ Add Contract Level Charges** to open it. It auto-expands on load when a draft already has charges saved. A **Remove Charges** button clears all rows and collapses the section.

The GP Summary now deducts the sum of all contract level charge estimated amounts from Net Contract GP alongside the packaging deduction.

On finalization, each charge row creates a `ContractLevelCharge` record with the billed/paid amount left blank for Finance Audit to fill in once invoices are settled.
