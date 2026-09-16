---
id: 2026-09-16-solicitation-type-length
title: Fixed — Solicitation Type no longer rejects longer set-aside types
published: true
publish_date: 2026-09-16
tags: [fixed, contracts]
critical: true
---

Save & Finalize was failing for contracts with a longer Solicitation Type
value — most visibly **Unrestricted** — with a generic "failed" popup that
didn't explain why. The underlying field only allowed 10 characters. It's
now been widened so Solicitation Type accepts any reasonably-sized value,
including Unrestricted, Small Business Set-Aside, and similar.
