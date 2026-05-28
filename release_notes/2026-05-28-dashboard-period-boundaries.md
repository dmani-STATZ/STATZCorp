---
id: 2026-05-28-dashboard-period-boundaries
title: Fix dashboard period boundary timezone bug
published: true
publish_date: 2026-05-28
tags: [fixed, contracts]
critical: false
---

Fixed a timezone bug where contracts awarded on the last day of the previous month were incorrectly included in "This Month" dashboard counts and reports. Monthly, weekly, quarterly, and yearly period boundaries now correctly reflect local time rather than UTC. The "New Contracts" detail export will also now show the correct date range in the Range Start/End columns.
