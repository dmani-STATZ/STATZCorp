---
id: 2026-06-23-intake-do-sharepoint-path
title: Intake — Delivery Order SharePoint Folder Paths
published: true
publish_date: 2026-06-23
tags: [improved, contracts]
critical: false
---

Delivery Order drafts in the intake queue now automatically inherit their SharePoint folder path from the parent IDIQ contract's actual location rather than computing a path from scratch. When a DO arrives via DIBBS, the system immediately looks up the matching IDIQ and builds the correct nested folder path (`Contract {IDIQ}/Delivery Order {DO}/`). If the analyst changes the IDIQ match in the editor, the path updates automatically. Paths confirmed manually via the document browser are never overwritten.
