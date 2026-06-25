---
id: 2026-06-25-recalc-null-percentage
title: "Recalc Split now handles contracts with no percentages set"
published: true
publish_date: 2026-06-25
tags: [fixed, finance]
critical: false
---

Fixed an issue where the **Recalc Split** button on the Finance Audit page
would fail with "Some companies have no percentage set" on legacy contracts
where split percentages had never been explicitly assigned.

**What changed:** The recalc logic now handles three cases cleanly:
- All companies have no percentage → distributes 100% equally
- Some companies have no percentage → those companies share the remaining
  headroom (100% minus the explicitly-set total) equally
- If existing percentages leave no headroom for the unset companies, a
  clear error message is shown instead of a silent failure
