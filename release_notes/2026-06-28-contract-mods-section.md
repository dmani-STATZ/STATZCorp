---
id: 2026-06-28-contract-mods-section
title: Contract modifications now appear on the contract page
published: false
publish_date: 2026-06-28
tags: [new, contracts]
critical: false
---

## Contract page — Modifications section

Matched DIBBS contract modifications now appear at the bottom of the contract management page. Each row shows the mod date, contract price, a **View on DIBBS** link to the award-record page, and an **Acknowledge** button. After acknowledgement, the row shows who acknowledged it and when; re-clicking Acknowledge does not change the stamp.

## Intake — modifications no longer appear as new awards

The daytime we-won poll now classifies modification rows the same way as the nightly AW import: mods are stored in `dibbs_award_mod` and no longer create Intake draft skeletons as if they were new awards.
