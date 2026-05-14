---
id: 2026-05-14-queue-already-in-db-flag
title: Contract Queue — "Already in DB" Warning
published: false
publish_date: 2026-05-14
tags: [improved, contracts]
critical: false
---

Queue rows whose contract number already exists in the finalized contracts
database are now flagged with a yellow **Already in DB** badge. The badge
links directly to the finalized contract (opens in a new tab). The
**Start Processing** button is disabled for these rows to prevent duplicate
finalization errors.
