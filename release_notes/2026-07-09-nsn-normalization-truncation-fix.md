---
id: 2026-07-09-nsn-normalization-truncation-fix
title: Malformed NSNs no longer block deploys
published: true
publish_date: 2026-07-09
tags: [fixed, contracts]
critical: false
---

NSN catalog rows with typos or non-NSN identifiers in the NSN code field (drawing numbers, long part codes, etc.) no longer crash database migrations when the normalized form exceeds 13 characters.

Those rows are left with a blank normalized value instead of being truncated, and can be audited any time with `python manage.py list_unnormalized_nsns` for manual cleanup. Saving an NSN in the app uses the same rule, so the overflow cannot recur on edit.
