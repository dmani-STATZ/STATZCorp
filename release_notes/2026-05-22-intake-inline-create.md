---
id: 2026-05-22-intake-inline-create
title: Intake — Inline create from Match modal
published: true
publish_date: 2026-05-22
tags: [improved, contracts]
critical: false
---

The Match modal now has a **+ Add new** panel for Buyer, NSN, and Supplier. Click it to inline-create the canonical record and apply it to the draft in one step — no need to leave the editor.

- For new Buyers: enter the buyer description.
- For new NSNs: enter the NSN code (and optionally a description).
- For new Suppliers: enter the name and CAGE code (both required).

The parsed value pre-fills the obvious field (e.g. the parsed buyer text → Buyer description) so analysts don't retype. Create-and-apply happens inside the same database transaction — if anything fails, the new canonical row rolls back and nothing is half-created.

IDIQ and Contract are intentionally not creatable from the modal (they have richer required fields). Use the full forms in the Contracts app for those, then re-Match.
