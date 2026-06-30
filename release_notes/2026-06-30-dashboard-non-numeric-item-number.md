---
id: 2026-06-30-dashboard-non-numeric-item-number
title: Contracts Dashboard No Longer Crashes on Alphanumeric CLIN Numbers
published: false
publish_date: 2026-06-30
tags: [fixed, contracts]
critical: false
---

The Contracts Dashboard (`/contracts/`) could crash with a database conversion error when calculating active supplier counts if any open CLIN had a non-numeric item number (for example `0001AA`).

- Non-numeric item numbers are now safely excluded from the active-supplier aggregation instead of raising an error on SQL Server.
- Numeric CLIN item numbers continue to count toward active supplier metrics as before.
