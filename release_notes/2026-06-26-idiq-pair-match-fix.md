---
id: 2026-06-26-idiq-pair-match-fix
title: Fixed IDIQ pair matching creating hundreds of blank rows
published: true
publish_date: 2026-06-26
tags: [fixed, contracts]
critical: true
---

Fixed a bug in the IDIQ contract editor where clicking the **Match** button
on a newly added pair row (via "+ Add CLIN") caused hundreds of blank rows
to appear, making the contract unsaveable. The form would grow to thousands
of fields and all subsequent saves, cancels, and finalizations would fail
with an error.
