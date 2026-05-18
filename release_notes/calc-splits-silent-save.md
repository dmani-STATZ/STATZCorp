---
id: calc-splits-silent-save
title: Calc Splits — Correct Order of Operations
published: true
publish_date: 2026-05-14
tags: [fixed, contracts]
critical: false
---

## Calc Splits — Correct Order of Operations

Clicking **Calc Splits** now silently saves the CLIN first before asking the server to calculate the STATZ split value.

Previously, if the analyst had typed a new Quote Price without saving first, Calc Splits would use the old saved value and produce the wrong result, requiring a manual Save followed by a second Calc Splits click to get the correct number. The analyst now clicks once and gets the correct answer.
