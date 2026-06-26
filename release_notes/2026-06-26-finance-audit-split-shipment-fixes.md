---
id: 2026-06-26-finance-audit-split-shipment-fixes
title: "Finance Audit: Split breakdown and shipment row fixes"
published: false
publish_date: 2026-06-26
tags: [fixed, finance]
critical: false
---

Two bugs on the Finance Audit page have been resolved.

**Split breakdown missing CLINs added after contract creation.** When a CLIN
(such as a Miscellaneous adjustment) was added to a contract after the original
finalization, it had no split records. Clicking RECALC SPLIT would update the
company totals correctly but the CLIN would be invisible in the per-company
split breakdown accordion — causing the raw values to not reconcile to the
displayed total. RECALC SPLIT now creates missing split records automatically
and the breakdown reflects all CLINs.

**Shipment rows appearing below the supplier group subtotal.** When expanding
shipments via the shipments pill on a CLIN row, the expanded rows were rendering
below the supplier subtotal row instead of directly under their CLIN. Shipment
rows now appear in the correct position: between the CLIN row and the
charges/subtotal.
