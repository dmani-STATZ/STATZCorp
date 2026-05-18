---
id: 2026-05-18-processing-clin-accordion-match-restore
title: Processing — CLIN Stays Open After NSN/Supplier Match
published: true
publish_date: 2026-05-18
tags: [fixed, contracts]
critical: false
---

**Bug Fix — CLIN accordion state lost after NSN/Supplier match**

After matching an NSN or Supplier, the page reload previously collapsed all CLINs, leaving the analyst disoriented. The matched CLIN now automatically re-expands and scrolls into view after reload, and a success toast confirms what was matched. Affects `process_contract_form.html`, `nsn_modal.js`, and `supplier_modal.js`.
