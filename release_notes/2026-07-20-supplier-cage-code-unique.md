---
id: 2026-07-20-supplier-cage-code-unique
title: Supplier cage codes are unique and normalized
published: false
publish_date: 2026-07-20
tags: [improved, system]
critical: false
---

Supplier `cage_code` values are trimmed and uppercased, and sentinel placeholders
(`NONE`, `NO CAGE`, blank) are stored as NULL. A filtered unique index enforces
uniqueness for real codes only — missing cage codes remain allowed.
