---
id: 2026-05-27-finance-audit-payment-rollup
title: Finance Audit — Paid & Customer Pay roll up from shipments
published: true
publish_date: 2026-05-27
tags: [improved, finance]
critical: false
---

For CLINs that have shipments (marked with the blue "S"), Paid and Customer Pay are now calculated automatically from the shipments and are no longer edited directly on the CLIN — record those amounts on the shipment instead. CLINs that haven't been converted to shipments yet keep working exactly as before. This removes a behind-the-scenes duplication that could cause totals to drift.
