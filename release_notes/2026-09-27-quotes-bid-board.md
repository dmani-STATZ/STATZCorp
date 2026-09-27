---
id: 2026-09-27-quotes-bid-board
title: STATZ Quotes — Bid Board and DIBBS BQ file export
published: false
publish_date: 2026-09-27
tags: [new, sales]
critical: false
---

## What Changed
**STATZ Quotes** now takes a solicitation all the way to the DIBBS upload file.

- **Bid Board** lists every open solicitation with supplier quotes. Each line
  shows how many quotes came in and which one is picked for the bid (the
  lowest landed cost is picked automatically).
- **Compare** opens the quotes side by side: base cost, packaging, freight,
  landed cost, delivery against what the solicitation requires, and payment
  terms. **Select this bid** overrides the automatic pick.
- **Build bid** fills in the DIBBS bid from the selected quote and our CAGE
  settings. Every save runs DIBBS's checks (for example, remarks on an
  automated solicitation, or a part number that is not an approved source) and
  tells you exactly what to fix.
- **BQ Export** downloads the batch quote file for every bid marked ready. If
  DIBBS rejects an upload, reopen it from **Bid Board > Submitted**.

The Quotes menu now groups pages by phase of the quoting process.

## What You Need To Do
Before the first real upload, check one exported file with a single test bid
in DIBBS.
