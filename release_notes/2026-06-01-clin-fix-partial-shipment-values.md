---
id: 2026-06-01-clin-fix-partial-shipment-values
title: "CLIN Fix: Quote Value and Item Value now correctly written to partial shipments"
published: true
publish_date: 2026-06-01
tags: [fixed, contracts]
critical: false
---

**Bug Fix:** CLIN Fix — Quote Value and Item Value entered manually in the partial
shipment conversion pane are now correctly written to the created shipment. Previously
the typed values were ignored and the source CLIN's values ($0 on legacy CLINs) were
used instead.
