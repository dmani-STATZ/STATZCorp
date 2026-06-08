---
id: 2026-06-08-intake-contract-number-normalization
title: Intake contract numbers now stored in dashed format
published: true
publish_date: 2026-06-08
tags: [fixed, contracts]
critical: false
---

Contract numbers created through the DIBBS intake path are now stored in the
standard dashed DLA format (e.g. `SPE7L1-26-P-7653`) to match the format used
in the contracts database and SharePoint folder names.

Previously, DIBBS-sourced drafts stored undashed numbers (e.g. `SPE7L126P7653`),
which caused SharePoint folder lookups to fail and prevented duplicate detection
from matching against existing contracts.

Existing drafts in the queue have been corrected, and their SharePoint folder
status has been reset so they will be re-scanned automatically on the next Scan SP run.
