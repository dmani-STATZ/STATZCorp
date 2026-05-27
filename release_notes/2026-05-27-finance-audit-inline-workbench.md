---
id: 2026-05-27-finance-audit-inline-workbench
title: Finance Audit — inline workbench
published: true
publish_date: 2026-05-27
tags: [improved, finance]
critical: false
---
##  Finance Audit — inline workbench (Slice 2C)

- Retired header **Add Shipment**, **Add Finance Line**, and **Log Payment** buttons.
- Per-CLIN **+ Shipment** (logistics only) and **+ cost** (CLIN-level finance lines).
- Per-shipment **+ cost** and editable **Paid** / **Customer Pay** ledgers (add, edit, delete).
- CLIN Paid / Customer Pay are read-only on Finance Audit for all CLINs.
- Payment Activity panel is read-only.

## API

- `PATCH /contracts/api/payment-history/<payment_id>/update/` — edit ledger entry in place.
