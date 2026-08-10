---
id: 2026-07-24-competitor-supplier-intel-coverage
title: "Supplier Intelligence: coverage visibility and faster backfill"
published: false
publish_date: 2026-07-24
tags: [improved, sales]
critical: false
---

The Supplier Intelligence page (**Competitors Numbers → View Suppliers**) now
opens with a plain coverage line — *"Based on 14 of 308 awards analyzed
(4.5%)."* — measured against every award that competitor has won, not just the
ones already processed. Previously the page reported a percentage of the awards
it had already looked at, so a ranking built on two documents looked identical
to a complete one.

Award processing also runs a much larger batch per nightly cycle, so the
historical backlog for a newly watched competitor clears in a fraction of the
time it used to take.

Two notes on reading the page:

- A low coverage percentage means the ranking is provisional. Treat it as a
  sample, not a supplier list.
- Some award documents are no longer retrievable from DIBBS. Those are recorded
  and skipped rather than retried indefinitely, so coverage will not reach 100%
  for older awards.

Also fixed: awards whose processing had been permanently abandoned by an earlier
version of the fetch logic can now be re-queued instead of staying stuck.
