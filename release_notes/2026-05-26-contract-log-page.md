---
id: 2026-05-26-contract-log-page
title: Contract Log Page - Advanced Filtering and Cleaner Exports
published: true
publish_date: 2026-05-26
tags: [improved, contracts]
critical: false
---

**The Contract Log page now has a cleaner filter sidebar and more complete column-level search.**

- Filters now open from a left-side drawer with grouped fields for contract identifiers, contract details, CLIN data, and key dates.
- Added server-side filters for PO number, IDIQ contract, contract number, buyer, contract type, CLIN number, cage code, NSN, item description, I&A, FOB, and award/QDD/CDD/ship date ranges.
- The filter button now shows an active-filter count, and the drawer automatically opens when filtered results are loaded.
- The log table now shows `Qty / UOM` and includes Item Value for easier CLIN review.
- CSV and Excel exports now follow the same filter logic as the page, include the updated columns, and remove the legacy Tab # column.
- Contract-level dollar values now appear only on the first CLIN row for each contract, keeping totals aligned with Plan Gross behavior.
