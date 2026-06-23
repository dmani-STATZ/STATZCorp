---
id: 2026-06-16-open-in-explorer
title: Open Contract Folders in Windows Explorer
published: true
publish_date: 2026-06-16
tags: [new, contracts]
critical: false
---

Contract document folders can now be opened directly in **Windows Explorer** from two places in the contracts app.

**Contract Management page** — next to the **Documents** button, a small folder button opens the contract's SharePoint folder in Explorer in the same tab. If the contract still has a legacy file path, that button is disabled; hover for a tooltip explaining how to fix it (open **Documents** and click **Save Path to Contract**).

**Document browser** — use **Actions → Open Current Folder in Explorer** while browsing a folder, or select a single subfolder and choose **Open Selected Folder in Explorer**. These actions appear only when the folder maps to your locally synced OneDrive library.

Requires the STATZ desktop handler (`statzfile://` protocol) deployed to your workstation via IT.
