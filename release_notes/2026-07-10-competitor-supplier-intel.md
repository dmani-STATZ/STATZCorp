---
id: 2026-07-10-competitor-supplier-intel
title: Competitor Supplier Intelligence
published: true
publish_date: 2026-07-10
tags: [new, sales]
critical: false
---

**Supplier Intelligence** shows which entities a watched competitor sources from, based on DD Form 1155 award PDFs. Each award can yield multiple role-tagged CAGE or DoDAAC codes (contractor, manufacturer, OEM, packaging, buyer office, payment office, and more).

From **Competitors Numbers**, use **View Suppliers** on any row to open that competitor's breakdown: entity code / name, role, how many awards mention them, and the most recent award date — sorted so the most-used sourcing entities appear first. Buyer and payment-office DoDAACs are kept on file for audit but excluded from the sourcing ranking. Awards with no ranking-eligible entity are counted separately so coverage gaps stay visible.

Data is filled in the background (including a one-time backfill of watched competitors' award history), piggybacked on the nightly DIBBS awards scrape plus daytime catch-up batches. It does not run on click; allow time after adding a CAGE for results to appear.
