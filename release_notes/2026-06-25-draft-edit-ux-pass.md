---
id: 2026-06-25-draft-edit-ux-pass
title: "Draft Editor UX Pass — CLC Layout, Match Buttons, CLIN Accordion"
published: true
publish_date: 2026-06-25
tags: [improved, contracts]
critical: false
---

## Draft Editor UX Improvements

Several visual and interaction improvements to the draft editor:

**Contract Level Charges — Two-Row Layout**
Each charge entry now uses two rows instead of one cramped inline row.
Row 1 holds Label, Supplier (with match button), and CAGE.
Row 2 holds Estimated Amount, Invoice Number, and Payment Date.
The "+ Add Line" button is also narrowed to fit its text rather than
stretching full width.

**Match Button State**
All Match buttons across the editor (Buyer, NSN, IDIQ, CLIN Supplier,
CLC Supplier, IDIQ pair NSN and Supplier) now turn green and display
"✓ Matched" when a record is linked. The previous green pill badge
showing the matched record ID has been removed. For supplier matches,
a small Probation or Conditional flag chip still appears below the button
when applicable; clean matches show only the green button.

**CLIN Accordion**
Only one CLIN card can be expanded at a time. Expanding a card automatically
collapses all others. New CLINs added via "+ Add New CLIN" auto-expand
immediately.
