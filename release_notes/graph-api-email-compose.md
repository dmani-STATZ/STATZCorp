---
id: graph-api-email-compose
title: Contract Finalization — Graph API Email Compose
published: true
publish_date: 2026-05-15
tags: [new, contracts]
critical: false
---

Contract finalization no longer attempts to open a local email client via
`mailto:` links, which was broken on systems running New Outlook. After
finalizing, the main window returns immediately to the processing queue and a
new tab opens showing an Outlook-style email compose page pre-populated with
the contract details. The analyst fills in the recipient, reviews the message,
and clicks Send — the email is dispatched directly via Microsoft Graph API
(GCC High) from info@statzcorp.com. `GRAPH_MAIL_ENABLED` must be set to True in
the environment to activate sending; when disabled the page explains the
configuration requirement.

The email body now includes a line per CLIN showing supplier name and NSN,
and an optional packhouse line when assigned. Tab number has been removed from
the body. The SharePoint folder URL is now used in place of the legacy UNC file
path throughout the system — in the email, in the finalized Contract record,
and in the processing form — when a SharePoint folder has been confirmed for
the contract.
