---
id: 2026-10-19-on-time-delivery-report
title: New On-Time Delivery Report
published: false
publish_date: 2026-10-19
tags: [new, contracts]
critical: false
---

The On-Time Delivery Report replaces the old Access report. Open it from the **Contract Menu → On-Time Delivery Report**.

**What it shows.** Every CLIN whose contract (government) due date falls in the range you pick. Results are grouped by Buyer, CLIN Type, and IA (Origin / Destination). Each row counts:

- **Late / On-Time**: whether the shipment that completed the CLIN went out after the contract due date.
- **Late QDD / On-Time QDD**: the same check against the CLIN's supplier due date. If a CLIN has no supplier due date, it's left out of this pair and a note under the table tells you how many.

Cancelled contracts are left out. A Totals row and a Percent row sit at the bottom.

**Filters.** Buyers, CLIN types, and IA are checkbox lists (none selected means all). Type in the buyer box to narrow the list. **Clear** unchecks a list, and **Select All DLA** checks every DLA buyer, even ones the search box is hiding. The page opens on last month with Primary checked and both Origin and Destination on. The date range can be up to a year. Nothing runs until you click **Run Report**. The page URL saves your filters, so you can bookmark a run.

**Export.** **Export to Excel** downloads a workbook with a **Summary** tab (your filters, the grouped table, totals, and percents) and a **Detail** tab listing every CLIN with its dates and late flags.
