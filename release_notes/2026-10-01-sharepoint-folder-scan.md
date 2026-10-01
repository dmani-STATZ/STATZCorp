---
id: 2026-10-01-sharepoint-folder-scan
title: SharePoint contract folder scan (Stage 1)
published: true
publish_date: 2026-10-01
tags: [new, contracts]
critical: false
---

Superusers can monitor SharePoint contract folder inventory from **Contracts → Folder Scan**.

- **`scan_folders`** management command walks the configured SharePoint root via Microsoft Graph, stores a folder snapshot, matches folders to contracts and IDIQs, and optionally updates `sharepoint_drive_item_id`. Use `--apply` to run path fixes after a successful scan; `--force` abandons a stuck run.
- **`fix_folder_paths`** applies `files_url` corrections from the latest completed scan (`--all` or `--contract-id`, optional `--dry-run`).
- New field **`Contract.sharepoint_drive_item_id`** records the Graph item id when a contract matches exactly one scanned folder.
- Status page at `/contracts/folder-scan/` with SSH instructions and live log polling.
