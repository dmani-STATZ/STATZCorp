---
id: 2026-08-18-arcade-lights-out-par-fix
title: Lights Out par is now correct
published: false
publish_date: 2026-08-18
tags: [fixed, system]
critical: false
---

The daily Lights Out puzzle was scoring against a wrong par on roughly half of
all dates, so "over par" numbers on the arcade leaderboard were unreliable.

Par is the fewest possible moves for that day's board. Calculating it relies on
four "quiet patterns" — press combinations that leave the board exactly as they
found it. Three of the four were wrong, and two of those weren't valid board
positions at all, so the shortest solution was often missed.

**What this changes**

- Par is now the true minimum for every board. Checked against every date in
  2026: it was wrong on 176 of 365 days before this fix.
- Some days had a par nobody could reach — the board's best possible solution
  needed more moves than par claimed, so scoring 0 was impossible. Others had a
  par that was too generous and handed out negative scores for ordinary play.
- Because par decides which board gets picked for a date, **the daily puzzles
  themselves change.** Anyone partway through today's puzzle when this ships
  will see a different board.

**Notes for admins**

Scores already recorded keep the par they were played against and are not
recalculated — old and new Lights Out scores are therefore not directly
comparable. Say the word if you'd rather we rescore the history instead.
