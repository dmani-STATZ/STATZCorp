# CONTEXT.md — Backyard Marauder (arcade real-time subsystem)

## Backyard Marauder

Marauder is a real-time vertical shooter inside the `arcade` app, deliberately
outside the daily-puzzle framework (`registry.py` / `PuzzleGame` / `ArcadeAttempt`).
It must never be wired into that engine. The only permitted coupling is one-way:
`arcade/views.py::lobby()` imports `get_global_top()` from
`arcade/services_marauder.py` to render the lobby card.

Its models are `PilotProfile` and `MarauderRun`. **`MarauderRun.score` is
higher-is-better**, the inverse of `ArcadeAttempt.score` (lower-is-better).
Separate tables, separate services, separate templates.

Two leaderboards, both top-5:
- Global — all pilots, all time (`get_global_top`)
- Personal — one pilot's own best runs (`get_user_top`)

`arcade/services_marauder.py` is contractually coupled to
`static/arcade/js/marauder/const.js`. Constants marked `[SERVER]` in `const.js`
are mirrored there; changing one without the other causes honest runs to be
flagged.

Anti-cheat is layered deterrence, not prevention:
- Salted signed session token (namespace `arcade.marauder.v1`)
- Integrity checksum keyed by that token
- Plausibility bounds derived from client tunables
- Unique one-shot seeds (`MarauderRun.seed` UNIQUE)

**Phase 1 status: complete** (foundation + difficulty/scoring correction,
missing service module, salt isolation, unique seed, director ramp).

**Phase 2 outstanding:** replay-guard wiring in `views_marauder.py`,
`IntegrityError` → 409, rate limiting on `run_start`.
