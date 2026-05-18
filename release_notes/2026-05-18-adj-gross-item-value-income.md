---
id: 2026-05-18-adj-gross-item-value-income
title: Finance Audit — Adj Gross stabilized during contract execution
published: false
publish_date: 2026-05-18
tags: [improved, finance]
critical: false
---

**Finance Audit — Adj Gross stabilized during contract execution**

Adj Gross on a CLIN now uses Item Value as the income figure consistently throughout the contract lifecycle. Customer Pay (wawf_payment) is still tracked and visible but no longer replaces Item Value in the profit calculation. This prevents mid-execution contracts from showing artificially negative Adj Gross when partial customer payments have been received but supplier costs are not yet settled.
