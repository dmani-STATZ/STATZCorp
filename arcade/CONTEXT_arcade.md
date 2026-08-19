# CONTEXT_arcade.md — Arcade App Architecture & Domain Guide

## 1. Purpose & Scope
The `arcade` app is a hidden daily-puzzle arcade hosted within STATZWeb. It features a lobby shell, shared per-day deterministic puzzles, server-authoritative grading, leaderboard standings, and player handicap tracking.

Playable games: **Lights Out** (5×5), **Wordle** (5 letters / 6 guesses), **Nonogram** (authored picture logic, 5×5 / 10×10 / 15×15), and **Backyard Marauder** (real-time shooter, not a daily puzzle).

---

## 2. Total Isolation Constraint
The `arcade` app is totally isolated from all other domain apps (`contracts`, `intake`, `processing`, `sales`, `suppliers`, `products`, `core`, `reports`, `training`, `transactions`).

- **Allowed external imports:** Django (`django.*`), `settings.AUTH_USER_MODEL`, `settings.ARCADE_SEED_SALT`, `settings.ARCADE_WORDLE_EPOCH`, `settings.ARCADE_NONOGRAM_EPOCH`.
- **Only coupling point:** A 20-line vendored JS script (`static/js/arcade_trigger.js`) included in `templates/base_template.html` that triggers navigation to `/arcade/` on 7 clicks of the header logo within a 3.0-second rolling window.

---

## 3. Data Model & Storage

### `ArcadeAttempt` (`arcade/models.py`)
Stores daily attempt records per user per game.

- `user`: Foreign key to `settings.AUTH_USER_MODEL` (`on_delete=CASCADE`).
- `game_key`: CharField (`'lights_out'`, `'wordle'`, `'nonogram'`).
- `puzzle_date`: DateField (non-nullable, derived from `settings.TIME_ZONE`).
- `seed`: Hex digest generated via `derive_seed()`.
- `status`: `'in_progress'`, `'solved'`, `'failed'`, or `'abandoned'`.
  - `'failed'` is terminal (Wordle loss). Counted as completed for handicap/leaderboard.
  - Nonogram has **no fail state** — only scored solves.
- `par`: Lights-Out-only minimum solution weight. **Nullable** for other games.
- `moves_used`: Total raw moves/guesses submitted.
- `score`: Lower-is-better integer, **comparable only within the same `game_key`** (never across games).
  - Lights Out: `moves_used - par` (over par).
  - Wordle: guess count on solve, or **7** on loss / failed.
  - Nonogram: `round(active_ms / 1000) + max(0, mistakes - 2) * 30` (adjusted time; 2 free misses).
- `active_ms`: Accumulated active play time (idle-capped at 120,000 ms per move gap).
- `state`: `TextField` storing JSON string (`get_state()` / `set_state()`).
  - Nonogram keeps `mistakes`, `filled`, `marked`, and **`art_key`** here — no game-specific columns.

#### Constraints & Indexes
- `UniqueConstraint(fields=['user', 'game_key', 'puzzle_date'], name='uniq_arcade_attempt_per_day')`
- Composite index `idx_arcade_leaderboard`: `(game_key, puzzle_date, score, active_ms)`
- Composite index `idx_arcade_user_handicap`: `(user, game_key, status)`

### `WordleRejectedGuess`
Upsert log of `not_in_list` guesses (`word` unique, `hit_count`, timestamps). Read-only in admin, ordered by `hit_count` desc. Operators promote frequent hits into `arcade/wordlists/allow_extra.txt`.

---

## 4. Deterministic Puzzle Engine

### Seed Derivation (`arcade/puzzles/base.py`)
`derive_seed(game_key, puzzle_date)` generates SHA256 of `game_key|YYYY-MM-DD|settings.ARCADE_SEED_SALT`.
Random number streams use explicit local `random.Random(seed_int)` instances. Module-level `random.*` is forbidden.

### Lights Out Engine (`arcade/puzzles/lights_out.py`)
- **GF(2) Matrix Math:** 25x25 toggle matrix for 5x5 grid. Null space dimension is 2, producing 4 coset solution sets per board.
- **Fast Solver:** Uses precomputed GF(2) pivot masks (`PIVOT_SOLVER_MASKS`) for microsecond par evaluation.
- **Difficulty Bands:** Mon (6–7), Tue (8), Wed (9), Thu (10), Fri (11), Sat (12–13), Sun (9–10).
- **Redaction:** `client_payload()` returns grid and moves used, but never solution, par, seed, or nullspace data.

### Wordle Engine (`arcade/puzzles/wordle.py`)
- **Answer selection:** Fixed shuffle of `ANSWERS` from `derive_seed('wordle_order', ARCADE_WORDLE_EPOCH)`, then daily index `(puzzle_date - epoch).days % len(order)`. No repeats until the pool wraps. Order cached at import.
- **Grading (mandatory two-pass):** Pass 1 marks `correct` and consumes answer letters; Pass 2 marks `present` only while an unconsumed copy remains, else `absent`. Single-pass grading is incorrect for duplicate letters — do not "simplify".
- **Validation:** Guesses must be in `GUESSES`. Hard mode is OFF.
- **Redaction:** `client_payload()` never includes the answer while in progress. Answer is included only on terminal solve/fail (after persist).
- **Scoring:** solve → `len(guesses)`; loss → `7`.

### Word lists (`arcade/wordlists/`)
- Runtime: `answers.txt`, `guesses.txt`, `allow_extra.txt` loaded once by `arcade/puzzles/wordlist.py`.
- Build inputs only: `sources/*.csv`, `build_wordlist.py` (never read at request time).
- **MUST NOT** live under `arcade/static/` or any static finder path. Serving these files would expose every future answer.

### Nonogram Engine (`arcade/puzzles/nonogram.py`)
- **Authored art only.** No procedural generation. Random noise at 15×15 / 45% density is ~6% line-solvable; authored art at the same density is ~100%.
- **Art pack:** `arcade/puzzles/art_pack.py` — module-level `ART_PACK` / `PACK_BY_KEY`, validated at import. **Not static** — must never move under `arcade/static/` or `STATICFILES_DIRS`.
- **Flat rotation (not weekday tiers):** `_shuffled_keys()` + `art_for(puzzle_date)` uses `(puzzle_date - ARCADE_NONOGRAM_EPOCH).days % len(order)`. With only 4 hard pieces, tier-scheduling would repeat hard puzzles every ~2 weeks — worse than flat rotation. To switch to tiers later, edit **only** `_shuffled_keys()`.
- **`art_key` persisted at start (critical):** Pack growth changes `len(order)` and remaps every date. `apply_move`, scoring, and the gallery **must** read `state['art_key']` from the attempt — never recompute via `art_for(attempt.puzzle_date)`. Without this, adding one piece silently rewrites gallery history and mis-grades in-progress puzzles.
- **Scoring:** `score = round(active_ms / 1000) + max(0, mistakes - 2) * 30`. Two free misses; free-miss remainder is shown in the UI. X-marks are free annotations. No fail state.
- **Gallery:** `/arcade/nonogram/gallery/` — unlocks by solved attempts' persisted `art_key`. Locked tiles leak nothing (no name/size/shape). Today's unsolved piece looks like any other locked tile.
- **Solver (`nonogram_solver.py`):** verification + tests only. Never on a request path. `arcade_verify_art` reports OK / WARN / SEEDS / FAIL.
- **Authoring:** fill 35–55%, structure over detail. See `docs/ART_AUTHORING.md`.
- **Open item:** 26 pieces ⇒ 26-day cycle. Growing the pack past ~60 is the highest-value follow-up.

---

## 5. Scoring & Handicaps (`arcade/services.py`)

- **Daily Leaderboard:** Ranked by `score` ASC, `active_ms` ASC, `completed_at` ASC for `solved` and `failed`.
- **Display wording:** Per-game via `PuzzleGame.format_score(value, attempt=None)` / `score_label` / optional `detail(state)` (no template `game_key` conditionals).
- **Handicap Aggregate:** Average of completed `score` values (min 5). Abandoned / stale `in_progress` contribute `game.stale_score` (Lights Out `10`, Wordle `7`, Nonogram `600`). Failed Wordle attempts contribute their stored score (`7`).
- **Suppression:** Handicap displayed only after ≥ 5 qualifying attempts; otherwise "N more to qualify".

---

## 6. Views & Client Contract
Generic `start` / `move` / `leaderboard` / `gallery` endpoints — no `if game_key ==` branching. Games raise `MoveRejected` for structured 400/409 reasons. Wordle `not_in_list` increments `WordleRejectedGuess` without breaking play. Gallery is opt-in via `PuzzleGame.has_gallery`.

---

## 7. Backyard Marauder — real-time shooter (NOT a PuzzleGame)

A vertical-scrolling arcade shooter living **inside** the arcade app but deliberately **alongside** the daily-puzzle framework, never inside it. It does not use `PuzzleGame`, `ArcadeAttempt`, `registry.py`, or the generic `start`/`move` endpoints.

- **Models** (`models.py`): `PilotProfile` (per-user economy: callsign, credits, total_runs, denormalized `best_score`) and `MarauderRun` (one row per completed run = the leaderboard). **`MarauderRun.score` is HIGHER-is-better** — the opposite of `ArcadeAttempt.score`. They never mix: separate tables, services, templates. `MarauderRun.seed` is **UNIQUE** (one-shot replay defense). Indexes `idx_marauder_global_top` (`status`, `-score`) and `idx_marauder_user_top` (`user`, `status`, `-score`) serve the two top-N queries; only `status='valid'` runs appear on boards.
- **Views** (`views_marauder.py`): `play`, `run_start`, `run_submit`, `leaderboard`. **Services** (`services_marauder.py`): salted token, checksum, derived plausibility bounds, leaderboard reads — imports no registry. Contractually coupled to `static/arcade/js/marauder/const.js` (`[SERVER]` constants).
- **URLs**: `/arcade/marauder/...` declared **before** the generic `<game_key>` catch-all in `urls.py`.
- **Leaderboard**: all-time. User sees global top-5 (score, username, date) + their own top-5 (score, date). No visibility into other users' run lists.
- **Anti-cheat** (deterrence, not prevention — a client-authoritative 60fps game cannot be fully cheat-proofed): distinct signing salt (`arcade.marauder.v1`, must not share the daily-puzzle signer namespace) → HMAC checksum keyed by the token (`CHECKSUM_FIELDS` must match `net.js::submitRun`) → plausibility bounds in `verify_submission` (flag borderline, reject absurd) → unique seed. Server owns the seed; the client PRNG (`rng.js`) is seeded from it, enabling future headless re-simulation of top scores.
- **Phase 1 complete.** Service module, difficulty ramp, distance scoring.
- **Phase 2 complete.** Replay-guard wiring in `views_marauder.py`, `IntegrityError` → 409, rate limiting on `run_start`.
- **Phase 3 complete.** Enforcer sprite corrected to a verified 28-wide, palindromic 12-row grid; global-leaderboard username rendering is now HTML-escaped; `autoFire` now defaults to `false`, matching the documented "hold left mouse" control. The collision-resolution swap-remove pattern in `resolveCollisions()` was investigated and confirmed correct; no logic fix was needed or applied there (comment-only note on the defensive `j >= enemies.count` guards).
- **Phase 4 complete.** Part 0 re-ran the Phase 3 checks against this repo: `autoFire: false` in `main.js`, Enforcer sprite `enforcer rows: 12 | malformed: 0`, `escapeHtml()` defined and used in `gameover.js::fillTable()`. Phase 3 is confirmed intact (the earlier review-copy discrepancy was a stale copy, not a missing landing). HUD bounty banner now reads `BOUNTY_SCORE_MULT` instead of a hardcoded `x2`. `__selftest__.html` now covers `director.js` determinism (same-seed identical wave sequence) and the three Phase 1 regressions (wave-size flattening, hauler-cap wave-ending, boss-skip-on-pool-full).
- **Opening-wave retune.** Playtest: first wave (~5s) dropped ~25–35 scouts at once. Cause was flat `GROUP_MIN=3..GROUP_MAX=5` on every purchase plus `THREAT_BASE=4`. `THREAT_BASE` is now 2 (late-game budget at t=200s is 182 vs old 184). Formation size ramps from `(1,2)` at t=0 to the old `(3,5)` by `GROUP_RAMP_SECONDS=90`, then holds — past 90s group size is identical to the previous build. `services_marauder.py` unchanged: anti-cheat ceilings track late-game max rate, which this does not alter.
- **Opening-difficulty pass 2.** The first pass still left wave 1 budget-limited (~9 enemies) and spatially full-width (`pincer` at both screen edges). `WAVE_PURCHASE_BASE` is now 1 so purchase count binds from wave 1 (1–2 enemies); the ramp to `WAVE_PURCHASE_CAP` stretches from ~250s to ~475s — deliberate, not a side effect. `EARLY_FORMATIONS` (`vFormation`, `centerRush`) excludes `pincer` until `PINCER_UNLOCK_S=20`. Low-tier crate chance ramps from 40% to the old 8% over `LOOT_RAMP_SECONDS=60` so powerups land before difficulty climbs. Late-game max rate / plausibility ceilings unchanged; `services_marauder.py` not touched. `__selftest__.html` adds `EARLY_FORMATIONS excludes pincer`.
- **Readability & fire-rate pass.** Native render surface raised from 320×240 to **480×360** (integer-upscale gives 3× = 1440×1080 on a 1080p monitor). Canvas HTML attribute, all HUD font sizes (6px→9px, banner 8px→12px), and pixel-position constants in `hud.js` scaled accordingly. `START_Y` moved to `VH - 60`. Hardcoded `330` OOB cull in `weapons.js` replaced with `VW + 10`. Skiff `holdY` and Enforcer hover Y scaled to maintain proportional screen positions. Scout `fireEvery` increased 1.6s→3.2s, Skiff `fireEvery` 1.9s→4.0s — opening waves no longer saturate the screen with bullets. Hauler and Enforcer fire rates unchanged. Server-side plausibility ceilings in `services_marauder.py` are unaffected (kill rate ceiling is not derived from `fireEvery`).
- **Client**: native ES modules under `static/arcade/js/marauder/` (entry `main.js`, `<script type="module">`, no bundler). Fixed 60Hz loop + interpolated render, 320×240 integer-upscaled canvas, procedural pixel-art sprite factory + WebAudio chiptune (no binary assets), object pools, threat-budget wave director. Logic-only modules are smoke-tested by `static/arcade/js/marauder/__selftest__.html` (rng/pool/collision/weapons plus `director.js` as of Phase 4).
- **Tests**: `tests/test_marauder.py`.
