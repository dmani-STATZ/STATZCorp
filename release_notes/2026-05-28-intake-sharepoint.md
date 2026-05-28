---
id: 2026-05-28-intake-sharepoint
title: Intake Queue — SharePoint Document Integration
published: true
publish_date: 2026-05-28
tags: [new, contracts]
critical: false
---

The intake queue now integrates with SharePoint across the full contract lifecycle — from first award notice through finalization.

**What's new:**

- **Company scoping** — The intake queue shows drafts for all companies you have access to. Each row displays a company badge so you always know which company a contract belongs to.
- **Automatic folder detection** — When a new award lands in the intake queue (via daily DIBBS scraping), STATZ automatically checks SharePoint to see if a folder already exists for that contract number.
- **Folder creation on PDF upload** — When you drop the award PDF onto the queue, STATZ creates the SharePoint contract folder automatically if one doesn't exist yet.
- **SP Folder column** — Each row in the intake queue now shows a SharePoint folder status indicator. A green folder icon means the folder is confirmed. Use the per-row rescan icon or the "Scan SP" toolbar button to check or refresh status.
- **Documents button** — Each queue row now has a "Docs" button that opens the SharePoint document browser for that draft's folder — the same browser you use on finalized contracts.
- **Path carries through to finalization** — When you finalize a draft, the confirmed SharePoint folder path is automatically saved to the new contract's files_url. No manual copy-paste needed.
