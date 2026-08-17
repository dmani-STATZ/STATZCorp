---
id: 2026-08-17-nsn-portal-search-nonstandard-codes
title: NSN Portal Search Finds Internal Part Codes
published: true
publish_date: 2026-08-17
tags: [fix, products, nsn-portal, search]
critical: false
---

NSN Portal search now finds internal/non-government part codes (not just 13-digit NSNs).

## What's Fixed

- Typing an internal catalog code in the omnibox (for example `RSM-B-BL-EZ` or `AAA-B-R`) returns the matching NSN row instead of "No matches."
- Dashless input against the same codes also works (for example `RSMBBLEZ`).
- Codes that normalize to five characters no longer dead-end in the CAGE supplier path when no supplier or SAM hit exists — search falls through to part/NSN text matching.
