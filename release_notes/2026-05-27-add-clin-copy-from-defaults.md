---
id: 2026-05-27-add-clin-copy-from-defaults
title: Add CLIN — "Copy From" defaults
published: false
publish_date: 2026-05-27
tags: [new, contracts]
critical: false
---

When adding a new CLIN to a contract that already has CLINs, a "Copy from existing CLIN" dropdown appears at the top of the form. Selecting a source CLIN automatically populates Supplier, NSN, I&A, FOB, UOM, Unit Price, Price Per Unit, Payment Terms, PO #, Tab #, and Due Dates — no manual matching required. Item Number, Quantity, and financial totals are intentionally left blank for the new CLIN. Entering a Quantity now also auto-calculates Total Value and Quote Total without needing to click ReCalc. Match buttons on the NSN and Supplier fields now turn green with a checkmark once a value is selected (whether via the picker or copy-from), and revert to blue if cleared. CLIN PO Number is now also copied when using Copy From.
