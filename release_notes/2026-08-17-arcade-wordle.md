---
id: 2026-08-17-arcade-wordle
title: Arcade Wordle Daily Puzzle
published: false
publish_date: 2026-08-17
tags: [new, arcade, wordle]
critical: false
---

**Wordle** joins the STATZ Daily Arcade alongside Lights Out.

## What's New

- **Shared daily Wordle:** One 5-letter answer per day for everyone; six guesses; hard mode off.
- **Server-side grading:** Duplicate-letter marks use the mandatory two-pass rule (greens consume first). The answer never reaches the client until the attempt is finished.
- **Guess list + rejection log:** Invalid guesses are rejected and tallied in admin for later promotion into `allow_extra.txt`.
- **Unified scoring column:** Arcade attempts now store lower-is-better `score` (Lights Out over-par; Wordle guess count, or 7 on a loss). Lobby wording comes from each game’s `format_score()`.
- **Losses are first-class:** Failed Wordle attempts status `failed`, score 7, and rank below any win on the daily board.
