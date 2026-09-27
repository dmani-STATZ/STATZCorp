# AGENT.md — Backyard Marauder rules for AI sessions

- Never wire Marauder into `arcade/registry.py`, `arcade/puzzles/`, or
  `ArcadeAttempt`.
- Never modify Wordle, Nonogram, or Lights Out code when working on Marauder.
- Never copy leaderboard ordering logic between `ArcadeAttempt`
  (lower-is-better) and `MarauderRun` (higher-is-better).
- `CHECKSUM_FIELDS` in `services_marauder.py` and the joined array in
  `net.js::submitRun` must change in the same commit or every submission
  returns 403.
- Constants marked `[SERVER]` in `const.js` must change in the same commit as
  their mirrors in `services_marauder.py`.
- Do not change the Marauder signing salt without accepting that every
  in-flight run token dies on deploy.
- Edit unapplied `0004_marauder.py` in place; do not generate a `0005_*`
  migration unless `0004` has already been applied in the target environment.
- Nothing in the Marauder subsystem may import from the puzzle framework.
  The only allowed coupling is `lobby()` importing `get_global_top`.
