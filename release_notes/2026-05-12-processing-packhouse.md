---
id: 2026-05-12-processing-packhouse
title: Processing — Packhouse assignment
published: true
publish_date: 2026-05-12
tags: [new, contracts]
critical: false
---

# Unreleased

## Processing — Packhouse assignment

You can now assign a packhouse to a contract during processing. The "Packhouse" section appears after the contract details and before the CLIN list. Suppliers flagged as packhouses appear at the top of the picker, but you can select any supplier — the flag is a hint, not a restriction. Quote amount and notes captured here carry through to the finalized contract; payment tracking on the Contracts side is coming in a follow-up update.

**Processing — Packhouse cost reduces Plan Gross.** The packhouse quote amount is now subtracted from the contract's Plan Gross. Plan Gross recalculates live when you edit the quote.

**Processing — Compact Packhouse layout.** The Packhouse section is now a slim two-row layout that only shows the Quote and Notes fields after a packhouse is assigned. Editing the Quote updates Plan Gross immediately.

**Processing — Clearing a packhouse now also clears its quote and notes.** Previously, clearing only removed the packhouse name and left the quote and notes attached. Now all three fields clear together, the Plan Gross recalculates immediately, and a confirm dialog warns you first.

**Processing — Fixed "Assign Packhouse" button doing nothing.** The click handler was attaching after the page-ready event had already fired on large form pages, so it silently never ran. The button now opens the picker reliably. Delegation was moved to `document` capture phase and wired synchronously when the script loads so the handler cannot be skipped by init timing. The packhouse picker was converted from Bootstrap’s JS `Modal` API to the same full-screen `hidden` overlay pattern as the buyer/NSN/supplier modals so it appears above the sticky footer and layout stacking contexts.