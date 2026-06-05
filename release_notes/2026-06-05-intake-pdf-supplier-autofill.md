---
id: 2026-06-05-intake-pdf-supplier-autofill
title: Intake — Supplier and packhouse auto-populated from PDF
published: true
publish_date: 2026-06-05
tags: [improved, contracts]
critical: false
---

When a DLA Form 1155 PDF is ingested into the intake queue, supplier and packhouse names are now automatically pre-populated on the draft.

- **Supplier:** The parser reads "PLACE OF INSPECTION FOR SUPPLIES" from the form — first at the contract level as a default, then per-CLIN as an override. When found, the company name pre-fills the Supplier field so analysts can match without typing.
- **Packhouse:** The parser reads "PLACE OF INSPECTION FOR PACKAGING" using the same logic and pre-populates the Packaging section.

Analysts still need to use the **Match** button to link each to a canonical record. If the relevant block is absent from the PDF, the field stays blank for manual entry.
