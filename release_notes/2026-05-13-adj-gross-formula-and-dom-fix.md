---
id: 2026-05-13-adj-gross-formula-and-dom-fix
title: Finance Audit — Adj Gross formula corrected and payment link bug fixed
published: true
publish_date: 2026-05-13
tags: [fixed, finance]
critical: false
---

Two fixes to the Finance Audit page:

**Adj Gross formula corrected.** Adjusted Gross on each CLIN now reflects actual money flows when available. Previously, Adj Gross always used the contracted amounts (Item Value − Quote Value). It now uses actual payments when they exist — Customer Pay when the government has paid, Supplier Paid when we have paid the supplier — falling back to contracted amounts when not yet populated. This means Adj Gross becomes more accurate as a contract executes.

**Payment history links no longer disappear after save.** After saving a payment history entry on a CLIN, the clickable Quote Value, Paid, Item Value, and Customer Pay links on that CLIN row were disappearing until the page was refreshed. This is now fixed — all links remain active after a save.
