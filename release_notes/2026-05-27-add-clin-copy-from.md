---
id: 2026-05-27-add-clin-copy-from
title: Add CLIN — copy defaults from an existing CLIN
published: true
publish_date: 2026-05-27
tags: [new, contracts]
critical: false
---

**Add CLIN — copy defaults from an existing CLIN**

When you add a new CLIN to a contract that already has line items, a **Copy from existing CLIN** dropdown appears at the top of the form. Pick a source CLIN and the form fills in the shared details automatically — no page reload.

**What copies**

- Supplier and NSN (including the Match picker display)
- I&A, FOB, UOM, Unit Price, Price Per Unit
- Payment Terms, CLIN PO Number, Tab #, CLIN Due Date, and Target Ship Date

**What stays blank on purpose**

- Item Number, Item Type, Quantity, Total Value, Quote Total, and all shipment/payment fields — so each new CLIN keeps its own identity and totals.

**Other improvements on the same form**

- Entering **Quantity** now updates **Total Value** and **Quote Total** as you type; ReCalc buttons remain if you need to refresh manually.
- **Match** buttons on NSN and Supplier turn green with a checkmark when a value is set (picker or copy-from), and return to blue **Match** when cleared.
