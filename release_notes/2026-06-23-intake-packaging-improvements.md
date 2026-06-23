---
id: 2026-06-23-intake-packaging-improvements
title: Intake — Packaging Same-CAGE Suppression and Remove Button Fix
published: true
publish_date: 2026-06-23
tags: [improved, contracts]
critical: false
---

### Packaging Improvements

- **Parser: packhouse suppressed when same as supplier** — The PDF parser no
  longer populates the Packaging section when the packhouse CAGE matches the
  contract supplier CAGE. When the same company supplies and packages, they
  bundle it in their quote — a separate packhouse entry is not needed. Analysts
  can still add packaging manually at any time.

- **Bug fix: "Add Packaging" button no longer disappears** — Clicking
  "Remove Packaging" now correctly restores the "+ Add Packaging" button in the
  same page session. The removal is also persisted to the server immediately so
  the packaging card does not reappear on the next page reload.
