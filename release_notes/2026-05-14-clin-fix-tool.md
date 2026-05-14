---
id: 2026-05-14-clin-fix-tool
title: CLIN Fix Tool (Legacy Cleanup)
published: false
publish_date: 2026-05-14
tags: [new, contracts]
critical: false
---

## CLIN Fix Tool

A new **Fix Legacy CLINs** page lets you clean up legacy contract data imported from the old Access database. In Access, "subcontract" was a junk-drawer term — packaging, trucking/freight, and partial shipments were all entered as subcontract rows. On import to STATZ those became plain CLINs. This tool routes them to their correct destinations.

## Where to find it

On any contract's management page, look for the small wrench icon button next to the **Contract Line Items** section header. Hover for the tooltip "Fix Legacy CLINs."

## What it does

For each CLIN on a contract, choose a destination:

- **Contract Packaging** — for legacy packhouse entries (only available if the contract has no packaging yet).
- **Finance Line** — for trucking, freight, labels, or miscellaneous costs.
- **Partial Shipment** — for entries that are actually partials of another CLIN on the same contract.
- **Delete** — for garbage rows (a reason is required for the audit log).

You can also leave a CLIN as-is.

## How it works

- All decisions configure in a fixed pane on the right side of the page and commit together when you click **Save All Conversions**.
- Your work autosaves continuously — close the tab and your decisions come back when you return.
- The widget in the upper area shows other contracts where you have unsaved drafts so nothing gets forgotten.
- Notes attached to a converted CLIN are automatically moved to the contract with a `[Migrated from CLIN xxxx]` marker.
- Payment History entries on a converted CLIN are deleted (the count is logged in the audit trail).
- A permanent audit record is written for every conversion (`ClinReclassificationLog`).

## Sunset note

This tool is scheduled for removal once the cleanup is complete. Treat it as a one-off feature, not a permanent part of the app.
