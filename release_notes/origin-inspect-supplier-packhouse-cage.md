---
id: origin-inspect-supplier-packhouse-cage
title: Origin Inspect — Supplier & Packhouse CAGE Auto-Extraction
published: true
publish_date: 2026-05-14
tags: [new, contracts]
critical: false
---

When parsing a DD Form 1155 PDF, the system now extracts supplier and
packhouse CAGE codes from the "PLACE of INSPECTION for SUPPLIES" and
"PLACE of INSPECTION for PACKAGING" blocks in Section B. The supplier
CAGE is stored per-CLIN and used during processing to guide supplier
matching. The packhouse CAGE is stored at the contract level; on the
process form it appears as a read-only hint near the packhouse picker
and automatically prefills and fires the packhouse modal search so
analysts can locate the correct packhouse with one click instead of
typing manually.
