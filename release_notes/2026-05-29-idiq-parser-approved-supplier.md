---
id: 2026-05-29-idiq-parser-approved-supplier
title: Intake IDIQ Parser — Auto-extract approved supplier from PDF
published: true
publish_date: 2026-05-29
tags: [improved, contracts]
critical: false
---

When an IDIQ PDF is ingested, the parser now attempts to extract the approved manufacturer/supplier name, CAGE code, and part number from Section B of the award document.

If found, the supplier is pre-populated as the first row in the CLINs (pairs) table on the IDIQ draft editor. Analysts still need to use the **Match** button to link it to a canonical Supplier record. Part number is captured when present (e.g. SMTC-18) — many IDIQ documents do not include a part number, so that field will be blank in those cases.
