---
id: 2026-06-01-clin-fix-partial-shipment-values
title: "CLIN Fix: Quote Value, Item Value, and UOM now correctly written to partial shipments"
published: true
publish_date: 2026-06-01
tags: [fixed, contracts]
critical: false
---

**Bug Fix:** CLIN Fix — Quote Value, Item Value, and UOM entered manually in the partial
shipment conversion pane are now correctly written to the created shipment. Previously
those typed values were ignored and the source CLIN's values ($0 / blank on legacy CLINs)
were used instead. Also fixes UOM entered in the conversion pane not being saved to the
created shipment.
