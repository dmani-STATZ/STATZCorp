---
id: 2026-06-03-report-request-email-notifications
title: Report Request Email Notifications
published: false
publish_date: 2026-06-03
tags: [new, system]
critical: false
---

Report request notifications: When a user submits a report request, an email is automatically sent to the reports admin with the requester CC'd. When the admin fulfills the request, an email is sent to the requester with the admin CC'd. Notifications are delivered via Microsoft Graph API and require `GRAPH_MAIL_ENABLED=True`.
