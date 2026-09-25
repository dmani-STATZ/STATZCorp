---
id: dibbs-bq-template-integrity
title: DIBBS BQ Template Integrity Fixes
published: false
publish_date: 2026-09-25
tags: [fixed, sales]
critical: false
---

## What Changed
Two defects in the daily DIBBS import were corrupting the stored BQ batch-quote
template that the bid export relies on.

**The 121-column template was never refreshed on re-import.** Every solicitation
line keeps a verbatim copy of its BQ row so the export can overlay our bid data
onto DIBBS's own template. That copy was only ever written for brand-new lines.
For any line that already existed — a re-import of the same date, or a
solicitation carried across days — the value was assigned but silently dropped
before it reached the database. Affected lines kept an empty template forever,
and exporting a bid for one failed outright with "no BQ template stored."

**The DIBBS files were being read with the wrong character encoding.** DIBBS
publishes the IN, BQ and AS files as ISO-8859-1, but the importer read them as
UTF-8. Any byte above the plain ASCII range — a degree sign in a nomenclature,
for instance — was replaced with a placeholder character and stored that way.

## Why It Matters
The first defect meant bid export could fail on solicitations that had been in
the system for more than a day, with an error message that pointed at the import
rather than the real cause. The second quietly degraded item descriptions and the
export template itself.

## What You Need To Do
Nothing for new imports — both are fixed going forward.

Lines that already hold a placeholder character in their stored template only
heal on re-import of that date. The original file bytes are not retained, so
there is no way to repair them in place. If a specific solicitation matters,
re-run the import for its date.
