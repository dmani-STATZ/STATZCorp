---
title: CLIN Type Added to Contract Notification Email
date: 2026-05-22
app: processing
type: improvement
---

**Contract notification emails now include CLIN item type.**

Each CLIN line in the finalization notification email now includes the 
CLIN type (e.g. FAT, PLT) so contract managers can immediately identify 
inspection and testing requirements without opening the contract.

Format: `CLIN: 0001,  Type: FAT,  Supplier: ...,  NSN: ...`
CLINs with no type set display as `Type: N/A`.
