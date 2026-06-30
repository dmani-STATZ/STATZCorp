---
id: 2026-06-30-closed-by-closed-on-headers
title: Closed By / Closed On Displayed in Contract Headers
published: true
publish_date: 2026-06-30
tags: [improved, contracts]
critical: false
---

Closed contracts now show **who closed them and when** directly in the contract header — no need to navigate to the Close page to find this information.

- **Contract Management** header grid: two new read-only fields — *Closed By* and *Closed On* — appear alongside the existing status/date fields. For Open or Cancelled contracts the fields show an em dash.
- **Finance Audit** header bar: the meta line now appends `· Closed mm/dd/yyyy · by Full Name` when the contract status is Closed. Open and Cancelled contracts are unaffected.

No new model fields or database migration are required. The data comes from the existing `Contract.closed_by` and `Contract.date_closed` fields, which are already set by the Close Contract action.
