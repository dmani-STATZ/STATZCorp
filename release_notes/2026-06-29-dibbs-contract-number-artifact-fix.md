---
id: 2026-06-29-dibbs-contract-number-artifact-fix
title: Fix DIBBS contract number HTML artifact stripping
published: true
publish_date: 2026-06-29
tags: [fixed, sales]
critical: false
---

Fixed a defect where DIBBS-scraped contract numbers were stored with a trailing `»` HTML navigation character in `dibbs_award_mod` and `dibbs_award`. This caused contract mod matching to silently fail — `matched_contract` remained NULL, so the Modifications section on the contract management page showed no mods for affected contracts. The hot-poll HTML parser now correctly prefers the clean URL-derived contract number when a mismatch is detected, and defensive stripping has been added to the normalizer as a belt-and-suspenders guard. A T-SQL cleanup script and a `rematch_unmatched_mods()` utility are provided to repair previously stored dirty records and retroactively match them to their contracts. Additionally, Playwright system dependency installation has been moved to a background process after Gunicorn starts, reducing cold-start time from ~215 seconds to under 30 seconds.
