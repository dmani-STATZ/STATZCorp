---
id: clin-split-save-fix
title: CLIN Splits — Save and Edit Fix
published: true
publish_date: 2026-05-14
tags: [fixed, contracts]
critical: false
---

## CLIN Splits — Save and Edit Fix

Split rows added via **Add Split** (e.g. PPI entries) are now correctly saved when the analyst clicks **Save CLIN**. Previously they were silently dropped.

Additionally, the STATZ split value is no longer automatically recalculated after every Save CLIN — it now only recalculates when the analyst explicitly clicks the **Calc Splits** button, preventing manual split edits from being overwritten.
