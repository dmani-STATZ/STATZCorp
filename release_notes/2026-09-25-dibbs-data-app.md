---
id: 2026-09-25-dibbs-data-app
title: DIBBS data now lives in its own app
published: false
publish_date: 2026-09-25
tags: [improved, sales]
critical: false
---

## What Changed
Everything we collect from DIBBS — daily solicitation imports, award records,
notices, competitor numbers and our CAGE settings — has moved into a dedicated
**DIBBS Data** area. The sidebar entry that used to read **STATZ Sales** now
reads **DIBBS Data**, and its pages live under `/dibbs/`. Old `/sales/...`
bookmarks forward automatically to the same page.

The unused Sales quoting screens (solicitation triage, RFQ queue, bid builder,
supplier matching) have been removed. Quoting is being rebuilt in the **STATZ
Quotes** app, which now receives every new DIBBS import automatically.

## Why It Matters
All historical DIBBS data was kept exactly as it was — nothing was re-imported
or lost. Separating the data feed from the quoting tool means the quoting
workflow can change without touching the nightly DIBBS imports.

## What You Need To Do
Nothing. Update any bookmarks to `/dibbs/` when convenient.
