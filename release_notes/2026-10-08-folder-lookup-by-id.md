---
id: 2026-10-08-folder-lookup-by-id
title: Contract and IDIQ folders follow SharePoint moves
published: true
publish_date: 2026-10-08
tags: [improved, contracts]
critical: false
---

Documents and **Open in Explorer** now resolve contract and IDIQ SharePoint folders by Graph drive item ID first, so folders still open correctly after they are moved or renamed in the library (for example into **Closed Contracts**) even when the stored path in the app is outdated.

The folder scanner also backfills IDIQ drive item IDs on the next `scan_folders` run.
