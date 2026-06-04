---
id: 2026-06-04-dfas-import-overhaul
title: "DFAS Payment Import: Matching Fix & Shipment Integration"
published: true
publish_date: 2026-06-04
tags: [improved, finance]
critical: false
---

Delivery-order contracts with a Call No. P-modifier suffix (e.g. `P00005`) now
auto-match correctly  the suffix is stripped before searching, removing the most
common cause of No Contract Match rows. Existing unresolved batches can be
re-processed using the new Re-run Matching button on the review page.

Finalization now routes payments correctly for CLINs that have shipments 
payment is applied to the matched shipment and rolls up to the CLIN, consistent
with how payments are recorded on the Finance Audit page. Legacy CLINs without
shipments continue to use the direct-on-CLIN path.
