---
id: 2026-09-28-supplier-capabilities
title: Supplier NSN & FSC capabilities, with bulk import
published: true
publish_date: 2026-09-28
tags: [new, sales]
critical: false
---

## What Changed
The NSN and FSC lists that decide which suppliers get matched to a solicitation now have a home of their own. You can see them, edit them and bulk-load them, from either side.

**In Quotes:** a new **Capabilities** page lists every supplier with a list, with counts. Click a supplier to open its list in a drawer. **Import pairings** takes a spreadsheet from another system (CSV or Excel) where each row names its supplier by CAGE or name.

**In Suppliers:** each supplier's page has a new **NSN & FSC Capabilities** section showing the same list and the same paste box. Change it in either place and it changes in both.

**Pasting a supplier's list:** pick a supplier, paste the NSNs and FSCs they sent (or drop their file), and review before anything is saved.

## What You'll Notice
- Before anything is saved you see what is new, what is already on file, anything that could not be read, and **how many open solicitations it would match** (and how many move from Unmatched to Matched).
- Supplier names and CAGEs in a file are matched against the supplier directory. Anything it cannot place waits for you to pick a supplier or skip it.
- After an import, open solicitations are re-matched straight away.
- Every import is logged on the Capabilities page with **Undo**, which removes exactly what it added along with the solicitation links it created.
- Removing an NSN or FSC drops the links it justified on open solicitations nobody has started working. Manual links and worked solicitations are never touched.
- The solicitation workspace has an **NSN/FSC** link on each supplier card that opens that supplier's list without leaving the page.

## Action Required
Editing capabilities needs Quotes access, even from a supplier page. Anyone without it sees the counts only.
