---
id: 2026-08-17-arcade-nonogram
title: Arcade Nonogram + Art Gallery
published: false
publish_date: 2026-08-17
tags: [new, arcade, nonogram]
critical: false
---

**Nonogram** joins Lights Out and Wordle as the third STATZ Daily Arcade game, with a personal art gallery.

## What's New

- **Daily Nonogram:** Shared authored puzzle per day (5×5 / 10×10 / 15×15). Flat pack rotation at launch — not weekday tiers.
- **Adjusted-time scoring:** `round(active_ms / 1000) + max(0, mistakes - 2) * 30`. Two free misses are visible in the UI; X-marks are free. No fail state.
- **Art gallery:** Solving permanently unlocks that piece. Names stay hidden until solved; locked tiles leak nothing.
- **Art pack + verify command:** Authored pack in `arcade/puzzles/art_pack.py` (not static). `arcade_verify_art` checks line-solvability and fill %. Solver is verification-only — never on a request path.
- **Pack-growth safety:** Each attempt stores `art_key` at start so adding art remaps only future dates, not gallery history or in-progress grading.
