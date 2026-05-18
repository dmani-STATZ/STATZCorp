---
id: 2026-05-15-finance-audit-packaging-variance
title: Finance Audit — Packaging Variance
published: true
publish_date: 2026-05-15
tags: [improved, finance]
critical: false
---

**Finance Audit — Packaging Variance:** The Packaging line on the Finance Audit summary now reflects only the variance between quoted and actual packaging cost (`amount_paid − quote_amount`). If no payment has been recorded, the row is hidden and contract adj gross ignores packaging (the quote is already captured in Plan Gross). Paid above quote (positive variance) shows in red as an overage; paid below quote (negative variance) shows in green as savings. Previously the full quoted or paid amount was deducted here, which double-counted the quote that Processing already applied to Plan Gross.
