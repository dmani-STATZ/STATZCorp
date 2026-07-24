---
id: 2026-07-24-dibbs-award-scrape-recovery
title: DIBBS award scraping restored
published: true
publish_date: 2026-07-24
tags: [fixed, sales]
critical: false
---

Nightly DIBBS award imports had stopped completing for several award dates. That path is being restored so missed dates are picked up again on the next runs.

One problem date no longer stops the rest of the night’s work — the job continues through the queue, and only a streak of repeated failures will pause the run so we can investigate without hammering DIBBS.
