---
id: 2026-06-10-reports-notification-sender-fix
title: Report notifications now send from the correct email address
published: true
publish_date: 2026-06-10
tags: [fixed, system]
critical: false
---

Report request notifications (new request submitted, report ready) were
incorrectly sending from the Statz Quotes address instead of the STATZ
info address. This has been corrected — notification emails now arrive
from `info@statzcorp.com` as intended.
