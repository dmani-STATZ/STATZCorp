---
id: 2026-05-18-shipment-payment-clin-rollup
title: Finance Audit — Shipment payments roll up to CLIN
published: true
publish_date: 2026-05-18
tags: [improved, finance]
critical: false
---

**Finance Audit — Shipment payments now roll up to CLIN**

Logging a Customer Pay or Paid payment on a shipment now automatically updates the parent CLIN's Customer Pay or Paid totals. Each rolled-up entry appears in the CLIN's payment history with a note indicating which shipment it came from. Deleting a shipment payment entry also removes the corresponding CLIN entry and recalculates the total.
