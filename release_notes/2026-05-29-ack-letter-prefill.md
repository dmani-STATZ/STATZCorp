---
id: 2026-05-29-ack-letter-prefill
title: PO Acknowledgment Letter — smarter date and contact prefill
published: false
publish_date: 2026-05-29
tags: [improved, contracts]
critical: false
---

When opening a PO Acknowledgment Letter that has not yet been sent to the contract folder,
all fields now automatically refresh from the current contract data — including supplier
contact, address, and due dates. This means if you fix a supplier record or update a CLIN
due date, reopening the letter will reflect those changes automatically.

Due dates now pull from the correct CLIN types:
- **Target Ship Date** pulls from the earliest Production (P) CLIN.
- **FAT Due Date** pulls from the earliest CFAT or GFAT (C/G) CLIN.
- **PLT Due Date** pulls from the earliest PLT (L) CLIN.

Once the letter is sent to the contract folder, it is locked and will not be overwritten.
