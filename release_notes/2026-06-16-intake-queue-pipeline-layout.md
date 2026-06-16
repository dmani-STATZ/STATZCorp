---
id: 2026-06-16-intake-queue-pipeline-layout
title: Queue Page — Pipeline Column Layout
published: true
publish_date: 2026-06-16
tags: [improved, contracts]
critical: false
---

Reordered columns: Company, Type, Contract Number, Award Date, Pipeline, Actions.

Added Award Date column sourced from `draft.data['award_date']`.

Replaced the separate Status, PDF, and SP Folder columns with a single Pipeline column showing four progressive step nodes: PDF → SP Folder → In Progress → Ready.

PDF node is now interactive: DIBBS drafts — click to fetch PDF from DIBBS; manual drafts — click to scroll to the upload zone.

SP Folder node is now interactive: click to trigger a per-row SharePoint rescan.

Docs button is now icon-only (folder icon with tooltip).

Removed supplier flag chips from queue rows.
