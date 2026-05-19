---
id: 2026-05-19-finance-audit-totals-refresh
title: Finance Audit — Totals Row Now Updates Without Page Refresh
published: true
publish_date: 2026-05-19
tags: [fixed, finance]
critical: false
---

The Totals row at the bottom of the CLINs table on Finance Audit now updates 
immediately when you log a payment or add a finance line — no page refresh 
needed. Previously the Totals row stayed stale until F5, even though the 
individual CLIN rows and Contract Summary card were updating correctly.

Shipment-level payment saves now also correctly refresh the parent CLIN row 
and Totals row.
