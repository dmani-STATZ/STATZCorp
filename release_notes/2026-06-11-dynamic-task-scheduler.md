---
id: 2026-06-11-dynamic-task-scheduler
title: Background Tasks Now Run on Independent Schedules
published: true
publish_date: 2026-06-11
tags: [improved, system]
critical: false
---

Background tasks no longer share a fixed 15-minute clock. Each task now runs on its own schedule — RFQ sending and AI generation check in every 5 minutes, award polling every 15 minutes, and calendar sync once an hour. The system also detects and automatically recovers from any task that gets stuck, logging a diagnostic counter for visibility into repeat offenders.
