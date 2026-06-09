---
id: 2026-06-08-queue-company-fix
title: Enforce and Propagate Active Company in Queue Processing
published: false
publish_date: 2026-06-08
tags: [fixed, system]
critical: false
---

- **Bug Fix**: Fixed an issue where contracts created via "Start New Contract" or processed/finalized from the queue pipeline did not correctly inherit the active company, resulting in them defaulting to company ID 1. The active company is now correctly validated on creation and propagated through `QueueContract`, `ProcessContract`, `ProcessClin`, and the final `Contract` or `IdiqContract` record.
- **New Feature**: Added a staff-only API endpoint (`/processing/queue/<queue_id>/update-company/`) allowing administrators or staff users to correct the company on any `QueueContract` item, with changes automatically cascading to any active `ProcessContract` and associated `ProcessClin` rows.
