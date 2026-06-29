---
id: 2026-06-29-block16-supplier-cage-extraction
title: Supplier CAGE auto-populated from Block 16 on new DLA awards
published: true
publish_date: 2026-06-29
tags: [improved, contracts]
critical: false
---

DLA has begun including the supplier CAGE code in the Block 16 "Reference your"
field on DD Form 1155 awards. The intake PDF parser now extracts this CAGE and
uses it as a fallback to pre-populate the supplier match field on every CLIN
(and IDIQ approved pair) when no more specific PLACE OF INSPECTION block is found.

This reduces manual lookup steps for analysts on newly ingested awards.
