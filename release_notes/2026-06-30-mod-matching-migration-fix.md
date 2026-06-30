---
id: 2026-06-30-mod-matching-migration-fix
title: DIBBS mod-to-contract matching backfill runs reliably on SQL Server
published: false
publish_date: 2026-06-30
tags: [fixed, system]
critical: false
---

The data migration that backfills `matched_contract` on historical DIBBS award modifications no longer fails on SQL Server with a pyodbc "connection is busy" error, so pending migrations can complete in production.
