---
id: 2026-05-29-idiq-editor-nsn-supplier-pairs
title: Intake IDIQ Editor — NSN + Supplier pairs with part number
published: true
publish_date: 2026-05-29
tags: [improved, contracts]
critical: false
---

The IDIQ draft editor now shows a single **CLINs** table where each row is one NSN paired with one Supplier, a Min Order Qty, and a Supplier Part Number — replacing the previous separate Approved NSNs and Approved Suppliers sections.

Each row finalizes to exactly one `IdiqContractDetails` record (two rows produce two records, not a cross-product). The new **Supplier Part Number** field (e.g. SMTC-18) is captured per NSN+Supplier pair and stored on `IdiqContractDetails`.
