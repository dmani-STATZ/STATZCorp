---
id: 2026-08-17-calendar-two-way-sharepoint-sync
title: Calendar events now sync both ways with SharePoint
published: false
publish_date: 2026-08-17
tags: [new, system]
critical: false
---

The home page calendar and the SharePoint calendar now stay in step in both directions.

Previously the sync only ran one way: events added in SharePoint appeared on the home page, but events added on the home page stayed in the web app and never reached SharePoint. Anyone working from the SharePoint calendar simply never saw them.

**What changed**

- Creating, editing, or deleting an event on the home page now updates the SharePoint calendar right away — no waiting for the hourly sync.
- Event times are corrected on the way out, the same way they already were on the way in, so an event shows the same start and end time in both places.
- Private events are never published to SharePoint. Marking an existing event private removes it from the shared calendar.
- The hourly background sync now also retries anything that failed to reach SharePoint, so a temporary outage no longer means a permanently missing event.
- The superuser "Sync SP" button now reports both directions: what came in from SharePoint and what went out to it.

**Notes for admins**

Pushing to SharePoint is on by default. The one-time backfill of events created before this release is off by default — turn on `SHAREPOINT_CALENDAR_BACKFILL_ENABLED` once you have confirmed new events are landing correctly.
