---
id: 2026-07-15-nightly-award-import-reliability
title: Nightly award import reliability improved
published: false
publish_date: 2026-07-15
tags: [fixed, sales]
critical: false
---

The nightly DIBBS award import could stop when production was running an older manually deployed stored procedure that did not populate the new PDF-link field. Startup now checks the live procedure for this deployment drift, and a scoped cleanup command safely removes staging rows left behind by failed import batches.

An administrator must still redeploy `sales/sql/usp_process_award_staging.sql` to Azure production through SSMS to fully resolve the production failure; application deployment cannot update this stored procedure automatically.
