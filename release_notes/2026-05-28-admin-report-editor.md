---
id: 2026-05-28-admin-report-editor
title: Admin Report Editor — Direct SQL Edits
published: true
publish_date: 2026-05-28
tags: [new, system]
critical: false
---

Superusers can now browse all reports by user, select any report, and directly edit its SQL, title, tags, and notes — saving a new immutable version immediately without requiring a user-submitted change request.

**What's new:**

- **Admin Report Editor** — A two-column workspace at `/reports/admin/editor/` lists every report in the library with user and title filters.
- **Direct version saves** — Edits create a new `ReportVersion` and repoint `active_version`; prior versions remain in history.
- **Queue shortcut** — The request queue sidebar includes an **Edit Reports Directly** link to open the editor.
