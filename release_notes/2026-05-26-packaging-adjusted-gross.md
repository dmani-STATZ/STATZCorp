---
id: 2026-05-26-packaging-adjusted-gross
title: Fix: Packaging cost now correctly deducted from Adjusted Gross
published: true
publish_date: 2026-05-26
tags: [fixed, finance]
critical: false
---

**Fix: Packaging cost now correctly deducted from Adjusted Gross**

The Adjusted Gross calculation on the Finance Audit page now correctly deducts the full packaging cost. Previously, packaging had no effect on Adjusted Gross until it was paid, and even then only the variance from quoted was applied. Now the full paid amount is deducted, or the quoted amount if not yet paid.

The Finance Summary label has been updated from "Packaging Variance" to "Packaging".
