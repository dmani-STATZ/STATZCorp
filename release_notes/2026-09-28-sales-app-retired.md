id: 2026-09-28-sales-app-retired
title: STATZ Sales has been retired
published: true
publish_date: 2026-09-28
tags: [improved, sales]
critical: false
---

## What Changed
The old **STATZ Sales** app has been removed. Its quoting screens (solicitation
triage, RFQ queue, bid builder and supplier matching) were never used for live
work. They've been replaced by **STATZ Quotes**.

The DIBBS data that Sales collected was kept. Solicitations, awards, notices,
competitor numbers and our CAGE settings now live in **DIBBS Data**
(`/dibbs/`). None of it was lost or re-imported.

## What You Need To Do
Nothing. Old `/sales/...` bookmarks forward to the matching DIBBS Data page.
Update them when convenient.