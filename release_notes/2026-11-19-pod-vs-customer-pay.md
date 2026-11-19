---
id: 2026-11-19-pod-vs-customer-pay
title: New POD vs Customer Pay Report
published: false
publish_date: 2026-11-19
tags: [new, finance]
critical: false
---

The new **POD vs Customer Pay** report lists deliveries that have proof of delivery but haven't been paid in full. Open it from **Contract Menu → POD vs Customer Pay**, just below the On-Time Delivery Report.

**Two lists.**

- **Not paid ($0.00):** delivered, and no customer pay has been recorded.
- **Underpaid:** delivered, some customer pay has come in, but it is at least one cent short of the item value. Differences of less than a cent don't count.

Each row shows the contract (click it to open Finance Audit), PO #, buyer, status, CLIN, supplier, POD date, days since POD, item value, customer pay, and the balance still owed. The oldest POD is at the top.

**CLIN or Shipment view.**

- **CLIN** (the default) shows one row per CLIN. A CLIN with shipments counts as delivered once it is marked POD complete. An older CLIN without shipments counts once its POD date is filled in.
- **Shipment** shows one row per shipment that has a POD date, even if the CLIN isn't marked POD complete yet. Shipment names match the shipments popup and Finance Audit.

**Status filter.** Pick a contract status, or leave it on **All**. All includes contracts with no status.

**Paging and export.** Each list shows 100 rows at a time and pages on its own. **Export CSV** downloads both lists for the current view and status, every row included. The first column says which list the row came from.
