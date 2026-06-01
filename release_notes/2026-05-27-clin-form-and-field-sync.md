---
id: 2026-05-27-clin-form-and-field-sync
title: CLIN — Smarter form defaults and live field updates
published: true
publish_date: 2026-05-27
tags: [improved, contracts]
critical: false
---

**Adding a new CLIN is faster.** When a contract already has CLINs, a **Copy from existing CLIN** dropdown appears at the top of the Add CLIN form. Select a source CLIN and the form fills in Supplier, NSN, I&A, FOB, UOM, Unit Price, Price Per Unit, Payment Terms, PO #, CLIN PO #, Tab #, and Due Dates automatically. The Supplier and NSN **Match** buttons turn green once a value is set and revert to blue if cleared. Item Number, Item Type, and Quantity are left blank — those are unique to the new CLIN. Entering a Quantity also auto-calculates Total Value and Quote Total without needing to click ReCalc.

**Values stay in sync as you work.** Changing **Order Qty**, **Unit Price**, or **Price Per Unit** on a CLIN now immediately recalculates and saves **Total Value** and **Quote Total** — the updated values appear on the page without a reload and are fully recorded in change history. **Ship Qty** also updates automatically after any shipment is added, edited, or deleted. On CLINs that have shipments, Ship Qty is read-only — it is always the sum of the individual shipment quantities and is updated by editing the shipments directly.