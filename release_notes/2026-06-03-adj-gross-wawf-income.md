---
id: 2026-06-03-adj-gross-wawf-income
title: Finance Audit — Adjusted Gross now reflects actual government payment including interest
published: true
publish_date: 2026-06-03
tags: [fixed, finance]
critical: false
---

When the government pays more than the contracted item value (e.g. late-payment interest under the Prompt Payment Act), the extra amount now correctly flows into Adjusted Gross. Previously, Adj Gross was anchored to Item Value regardless of what was actually received. The fix: income uses the actual Customer Pay amount when recorded, and falls back to Item Value only when no payment has been entered yet. This affects the CLIN-level Adj Gross column, the contract summary Adj Gross, and the Split recalculation. No data migration required — the fix is purely in the calculation logic.
