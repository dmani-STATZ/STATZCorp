---
id: 2026-06-24-split-packaging-autorecalc
title: Split values now account for packaging at contract creation
published: false
publish_date: 2026-06-24
tags: [fixed, finance]
critical: false
---

Split values on the Finance Audit page now correctly reflect packaging
and contract-level charge deductions immediately after a contract is
finalized — no manual "Recalc Split" required.

Previously, split values were computed from the raw per-CLIN gross profit
without deducting packaging costs, causing a discrepancy between the
displayed split total and the Adj Gross.
