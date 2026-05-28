---
id: 2026-05-28-fix-select-distinct-sql-server
title: Fix SQL Server preview for SELECT DISTINCT queries
published: true
publish_date: 2026-05-28
tags: [fixed, reports]
critical: false
---

Fixed a bug where report SQL previews using `SELECT DISTINCT` failed on SQL Server with a syntax error near `DISTINCT`. Preview limits now inject `TOP N` in the correct position (`SELECT DISTINCT TOP N ...`) so deduplicated preview queries run successfully.
