---
id: 2026-10-19-on-time-delivery-report
title: New On-Time Delivery Report
published: false
publish_date: 2026-10-19
tags: [new, contracts]
critical: false
---

The On-Time Delivery Report replaces the old Access report. Open it from the **Contract Menu → On-Time Delivery Report**.

**What it shows.** Every fully shipped CLIN whose supplier due date falls in the range you pick. Results are grouped by Buyer, CLIN Type, and IA (Origin / Destination). Each row counts:

- **Late QDD / On-Time QDD**: whether the shipment that completed the CLIN went out after the supplier due date.
- **Late / On-Time**: the same check against the CLIN's contract due date.

Cancelled contracts and CLINs that are not fully shipped are left out. A Totals row and a Percent row sit at the bottom. If some CLINs have no contract due date, a note under the table tells you how many were left out of Late / On-Time.

**Filters.** Pick buyers (none selected means all), CLIN types, IA, and a supplier due date range of up to a year. **Clear Buyers** unselects every buyer, and **Select All DLA** selects every DLA buyer. The page opens on last month with Primary CLINs selected. Nothing runs until you click **Run Report**. The page URL saves your filters, so you can bookmark a run.

**Export.** **Export to Excel** downloads a workbook with a **Summary** tab (your filters, the grouped table, totals, and percents) and a **Detail** tab listing every CLIN with its dates and late flags.
