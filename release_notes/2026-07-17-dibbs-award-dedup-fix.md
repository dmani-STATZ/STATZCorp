---
id: 2026-07-17-dibbs-award-dedup-fix
title: DIBBS Award Parser Row Selection and Link Passthrough
published: false
publish_date: 2026-07-17
tags: [fixed, sales]
critical: false
---

We resolved a silent row-loss bug on the DIBBS nightly awards scraper where the first two data rows (Row 1 and Row 2) were skipped on direct-navigation pages due to a hardcoded row-offset slice (`all_trs[3:]`).

### Changes Implemented
- **Identity-based Row Selection:** Switched the scraper from using a hardcoded `[3:]` index slice to an identity-based row selector using the ASP.NET control span suffix `_lblAwardBasicNumber`.
- **Reconciliation Check:** Integrated a strict post-scrape reconciliation check comparing parsed row counts against the DIBBS expected row count label (`lblRecCount`). Scraper runs now fail loudly instead of silently committing partial batches if a mismatch is detected.
- **Link Passthrough Columns:** Added four new URL fields (`award_basic_number_url`, `award_basic_package_view_url`, `delivery_order_number_url`, `delivery_order_package_view_url`) to both `DibbsAward` and `DibbsAwardStaging` to persist verbatim grid URLs.
- **Database & Stored Procedure Sync:** Updated `usp_process_award_staging` to cleanly stage and carry forward these URL fields during insert, update, and faux-upgrade paths.
