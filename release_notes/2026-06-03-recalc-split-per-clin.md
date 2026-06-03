---
id: 2026-06-03-recalc-split-per-clin
title: Finance Audit — Recalc Split now distributes correctly across CLINs
published: false
publish_date: 2026-06-03
tags: [fixed, finance]
critical: false
---

Previously, each CLIN row for a company was stamped with the full company split total, causing the Split Summary to show multiples of the correct amount. The company's share is now distributed proportionally across CLINs by item value, so the per-CLIN rows add up to — rather than multiply — the company total.
