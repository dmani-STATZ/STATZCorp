---
id: 2026-08-18-non-dla-contract-numbers
title: Non-DLA contract numbers are now handled correctly
published: false
publish_date: 2026-08-18
tags: [fixed, contracts]
critical: false
---

Contract numbers that don't start with `SPE` — Army `W912PB` numbers, our own
`STATZ1` COTS and internal tracking numbers, and anything else outside DLA — are
now treated as valid throughout the system.

Previously the number-checking rules were written around DLA's `SPE` prefix.
Anything else was flagged as malformed, which had two effects:

- **DFAS payment imports could not match them.** A payment row for a non-DLA
  contract produced no match at all, so it had to be resolved by hand.
- **`STATZ1-…-N-…` numbers were rejected** even though that format is our own
  documented convention for internal and COTS contracts.

Numbers are still checked for the right shape — six-character activity code,
two-digit fiscal year, one-letter type, four-character serial — so genuinely
malformed input is still caught. Only the assumption that the contract had to be
DLA has been removed.

**Notes for admins**

Nothing stored changes. If DFAS rows for non-DLA contracts were previously left
unresolved, re-running the match on those import batches should now find them.
