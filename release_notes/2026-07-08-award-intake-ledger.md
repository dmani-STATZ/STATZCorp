---
id: 2026-07-08-award-intake-ledger
title: Award Intake Ledger tracks the full award-to-contract journey
published: false
publish_date: 2026-07-08
tags: [new, sales]
critical: false
---

We now keep a durable, queryable record of every DIBBS award we win — from the moment we first see it through to the day it becomes a live contract.

Previously, once an intake draft was finalized into a real contract, the draft (and its link back to the original award) was deleted, leaving no lasting trail of the award's lifecycle. The new **Award Intake Ledger** fixes that with one row per contract that records:

- when we first saw the award and whether it was a win for one of our CAGEs,
- whether an intake draft was created and whether it was worked,
- whether a modification record exists (and how many),
- when — and to which contract — it became live.

- The ledger updates automatically from the nightly award scrape, the daytime we-won poll, and at finalization, with a nightly reconciliation task as a full backstop.
- Lifecycle milestones are write-once — once a date is recorded it is never overwritten — so the history stays trustworthy.
- This first release delivers the backend and a one-time backfill of recent award batches; a dedicated read-only page to browse, filter, and export the ledger ships alongside it (see "Browse the Award Ledger from a new read-only page").
