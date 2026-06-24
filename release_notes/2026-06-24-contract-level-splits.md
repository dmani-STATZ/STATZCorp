---
id: 2026-06-24-contract-level-splits
title: Contract-level GP split with packaging deduction
published: true
publish_date: 2026-06-24
tags: [improved, contracts]
critical: false
---

GP splits are now managed at the **contract level** rather than
per-CLIN.

Enter company names and percentages once — they apply automatically
to every CLIN on the contract. The new **Contract GP Split** table
(above GP Summary) shows each company's total split value with a
breakdown by CLIN. Click a company row to expand or collapse its
detail lines.

When a contract includes packaging, each company's share of the
packaging cost is automatically deducted from their split total,
so the values shown reflect the actual net profit being allocated.

**Bug fix (same release):** Contract split percentages were not being
saved due to a silent failure in the dynamic input injection
mechanism. Splits now use standard named form inputs and submit
reliably on every save path.
