---
id: 2026-06-29-nsn-search-normalization
title: NSN search now works without dashes
published: true
publish_date: 2026-06-29
tags: [fixed, contracts]
critical: false
---

## What changed
The NSN lookup modal now finds records whether or not the analyst types the standard dashes in the NSN code. Entering `5995015690560` and `5995-01-569-0560` now return the same result.

Additionally, creating a new NSN via "Create & Use" normalizes the code to dashed canonical format (`XXXX-XX-XXX-XXXX`) before saving, preventing duplicate undashed records from being created when a dashed one already exists.

## Why
NSN codes are stored in dashed format (e.g. `5995-01-569-0560`). The search predicate was a substring match that required the query to be a substring of the stored value — a fully-digit 13-character query is never a substring of the dashed form, so results returned empty.

## Impact
- Intake IDIQ entry (approved pairs NSN lookup)
- CLIN NSN lookup on all draft types
- "Create & Use" NSN inline creation

## Files changed
- `intake/matchers.py` — `_normalize_nsn_code()`, `_search_nsn()`, `_create_nsn()`
- `intake/tests.py` — six new test cases
