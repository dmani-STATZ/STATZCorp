---
id: 2026-06-08-intake-company-fix
title: Intake Company Fix and Draft Reassignment
published: false
publish_date: 2026-06-08
tags: [fixed, contracts]
critical: false
---

- **Bug Fix**: Fixed an issue where contracts and IDIQ contracts finalized via the Intake app did not correctly carry the company from the DraftContract, resulting in them defaulting to company ID 1. They now correctly propagate the company through the finalization payload.
- **New Feature**: Added a staff-only API endpoint (`/intake/drafts/<pk>/update-company/`) allowing administrators or staff users to correct the company on any `DraftContract` item.
