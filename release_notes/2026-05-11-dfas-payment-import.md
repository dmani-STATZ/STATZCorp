---
id: 2026-05-11-dfas-payment-import
title: Import DFAS Payments from a File
published: true
publish_date: 2026-05-11
tags: [new, finance]
critical: false
---

You can now upload a DFAS payment export and import the payments in bulk instead of typing each one by hand. Find the new **DFAS Payment Import** option under the **Contracts** menu.

Upload the `.txt` file you download from DFAS. STATZ will parse each row, try to match it to a contract and CLIN, and show you a review page. From there you can:

- Confirm matches that STATZ found automatically (the common case)
- Pick a CLIN when STATZ found the contract but couldn't identify the line item
- Search for and assign a contract when no automatic match was found
- Skip rows that don't apply to STATZ, or that you want to handle later
- See and acknowledge possible duplicates (rows you've already imported in a previous file)

When you click **Confirm Import**, every matched row becomes a payment on the right CLIN — same as if you'd added it through the usual Payment History form, just much faster. Negative payments (DFAS reversals) are supported and clearly flagged.

Every import is kept on file. You can revisit prior imports from the **DFAS Payment Import** page to see what was imported, when, and by whom.
