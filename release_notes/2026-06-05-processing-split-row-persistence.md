---
id: 2026-06-05-processing-split-row-persistence
title: Processing — Split row immediate save and unsaved indicator
published: true
publish_date: 2026-06-05
tags: [improved, contracts]
critical: false
---

**Add Split** now immediately saves the new row to the database when the analyst enters a company name and tabs or clicks away — no longer requires a separate **Save CLIN** click to persist a brand-new split row.

All split rows that have unsaved edits now display a yellow **Unsaved** badge in the Actions column. The badge clears automatically when **Save CLIN** completes successfully.

Fallback behavior is preserved: if the immediate persist fails (e.g. network error), the row remains in DOM-only mode and **Save CLIN** will still catch it via the existing persist path.
