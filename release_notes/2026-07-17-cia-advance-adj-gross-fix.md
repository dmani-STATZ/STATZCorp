---
id: 2026-07-17-cia-advance-adj-gross-fix
title: Finance Audit — CIA advance payments now reduce Adjusted Gross
published: true
publish_date: 2026-07-17
tags: [fixed, finance]
critical: true
---

CIA advance rows (Contract Level Charges with `action_type='advance'`) were previously excluded from the deduction that reduces Adjusted Gross, on the assumption they were pre-payments that would reconcile elsewhere. In practice a CIA advance is real cash paid to the supplier, and on contracts where it covers part of a CLIN's cost (with the CLIN's own Paid amount holding only the remainder), that money was never subtracted from Adj Gross anywhere — overstating profit by the full advance amount.

Confirmed on contract SPE7L3-24-P-8222: a $76,185.84 CIA advance plus a $34,037.40 final payment together made up the $110,223.24 real cost of CLIN 0001. Adj Gross was showing $82,217.34; the correct figure is ~$6,031.50.

Fix: `charges_deduction` now sums `billed_paid_amount` (falling back to `estimated_amount`, which is always $0.00 for advances until funded) across **all** Contract Level Charge rows, not just `action_type='charge'`. This is consistent across `Contract.adjusted_gross`, the Finance Audit page and its async refresh endpoints, the supplier-grouped CLIN table, and split recalculation — an unpaid CIA advance still contributes $0 until it's actually funded. The Finance Audit CLIN table's Adj Gross cell for a CIA row now shows the negative deduction once paid instead of always showing "—". No data migration required — this is a calculation-logic fix only; Adj Gross will recompute correctly the next time each affected contract's page loads or Recalc Split is run.
