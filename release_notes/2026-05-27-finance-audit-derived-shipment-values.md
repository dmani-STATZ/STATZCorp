---
id: 2026-05-27-finance-audit-derived-shipment-values
title: Finance Audit — Derived Shipment Values
published: true
publish_date: 2026-05-27
tags: [improved, finance]
critical: false
---

## Finance Audit — shipment values now calculate automatically

A shipment's Quote Value and Item Value are now calculated from its quantity × the CLIN's unit price, instead of being typed in by hand. To change them, change the shipment's quantity.

For older contracts missing a unit price, a small **set unit price** option appears on those CLINs so new shipments can still be calculated correctly. Setting unit prices does not change amounts already stored on existing shipments — only new shipments and future quantity changes use the updated rates.

Paid and Customer Pay on shipments are unchanged in this release.
