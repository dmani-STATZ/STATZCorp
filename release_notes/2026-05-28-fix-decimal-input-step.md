---
id: 2026-05-28-fix-decimal-input-step
title: Fix decimal values rejected in field edit modal
published: true
publish_date: 2026-05-28
tags: [fixed, system]
critical: false
---

Fixed a bug where entering decimal values (e.g. `598.08`) in the field edit modal would trigger a browser validation error and block saving. Affected all numeric fields editable via the transaction modal, including Plan Gross and any other decimal-type fields.