---
id: 2026-10-20-idiq-duplicate-guard
title: Duplicate IDIQs are blocked, and unwanted IDIQs can be deleted
published: false
publish_date: 2026-10-20
tags: [fixed, contracts]
critical: false
---

You can no longer create or rename an IDIQ to a number that already exists. Dashes, spaces, and upper/lower case are ignored, so `SPE7L1-23-D-0099` and `spe7l1 23 d 0099` count as the same IDIQ. Closed IDIQs count too. The error tells you which IDIQ already exists and whether it's open or closed. If it's closed, reopen it instead of making a new one.

**Delete IDIQ.** The IDIQ page has a new **Delete IDIQ** button. Delete only works when nothing is linked to the IDIQ (no delivery orders, NSN / supplier pairs, notes, or scanned files). If anything is linked, the dialog lists it and the IDIQ stays.

**Close and Reopen.** **Close IDIQ** now asks you to confirm and shows what's linked to the IDIQ. A closed IDIQ has a **Reopen IDIQ** button. The Closed checkbox on the Edit page is gone; use these buttons instead.

**Fixed:** saving the IDIQ Edit page no longer shows an error page after your changes are saved.
