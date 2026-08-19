# AGENTS_arcade.md — Safe-Edit Rules for Arcade App

> **CRITICAL RULE:**
> **The arcade app imports nothing from other STATZWeb apps (`contracts`, `intake`, `processing`, `sales`, `suppliers`, `products`, `core`, `reports`, `training`, `transactions`). The only coupling point is the trigger script in `templates/base_template.html` (`static/js/arcade_trigger.js`).**

---

## 1. Architectural Boundaries & Rules

1. **Zero Cross-App Imports:**
   Never import from non-Django domain apps. External dependencies must strictly remain Django, `settings.AUTH_USER_MODEL`, `settings.ARCADE_SEED_SALT`, `settings.ARCADE_WORDLE_EPOCH`, and `settings.ARCADE_NONOGRAM_EPOCH`.

2. **No CDN Assets:**
   GCC High environment. All static CSS/JS must be vendored and served locally from `arcade/static/` or `static/`.

3. **No Global Random Calls:**
   Always instantiate local `random.Random` using `rng_for(seed)` (or an explicit local `Random` for one-time shuffles). Calling `random.seed()`, `random.randint()`, etc., directly at module level will corrupt deterministic puzzle generation across threads.

4. **MSSQL & MARS Safety:**
   Always materialize querysets with `list()` before nesting secondary queries or looping in views (e.g. `list(ArcadeAttempt.objects.filter(...).select_related('user'))`).

5. **JSON Redaction Safety:**
   `client_payload()` must **NEVER** expose solution sets, par values, nullspace masks, or seed data to the client while a puzzle is in progress. Wordle may include the answer **only** after terminal solve/fail. Nonogram may include `name` + full `grid` **only** after solve — never `art_key` while in progress.

6. **State Storage (`TextField`, not a native JSON column):**
   Model `ArcadeAttempt` uses `TextField` + `json.dumps`/`json.loads` (`get_state()` / `set_state()`) to prevent SQL Server vs SQLite ORM path divergence on JSON columns. Do not introduce `JSONField`.

7. **Score semantics:**
   Column is `score` (renamed from `over_par`). Lower is better. Comparable **only within** a `game_key`. Do not reintroduce `over_par` as a storage field. Do not add game-specific columns (e.g. `mistakes`) — keep them in `state`.

8. **Word lists are NOT static:**
   `arcade/wordlists/` must never move under `arcade/static/` or `STATICFILES_DIRS`. A 200 on `/static/arcade/answers.txt` is a security bug.

9. **Art pack is NOT static:**
   `arcade/puzzles/art_pack.py` must never move under `arcade/static/` or `STATICFILES_DIRS`. Clues reveal the solution by definition, but the pack must not be a URL-fetchable spoiler of upcoming puzzles.

10. **Wordle duplicate-letter grading is two-pass:**
    Greens consume first; yellows only from remaining unconsumed answer letters. Do not replace with a single-pass / naive `in answer` check.

11. **`allow_extra.txt` operator workflow:**
    Review `WordleRejectedGuess` admin (by `hit_count`), append approved words to `arcade/wordlists/allow_extra.txt`, restart the app (import-time load). No code change required.

12. **Nonogram `art_key` is immutable history:**
    Persist `art_key` on the attempt at start. Never re-grade or unlock gallery tiles by recomputing `art_for(puzzle_date)`. Pack growth remaps the date→art schedule; only tomorrow onward should shift.

13. **Nonogram solver is verification-only:**
    Do not call `line_solve` / `min_seeds` from views or `NonogramGame` request paths. Use `python manage.py arcade_verify_art` and pack tests.

14. **No procedural Nonogram generation:**
    Authored art only. See measured solvability (~6% random vs ~100% authored) in CONTEXT / `docs/ART_AUTHORING.md`.

---

## 2. Registry & Game Extensions

Adding a new game to `arcade/registry.py`:
1. Subclass `PuzzleGame` in `arcade/puzzles/<game_name>.py`.
2. Implement `generate()`, `initial_state()`, `apply_move()`, `is_solved()`, `is_failed()` (default False), `score_on_complete()`, `client_payload()`, `format_score(value, attempt=None)`, and set `score_label` / `stale_score`. Optional: `detail(state)`, `has_gallery` + `gallery_tiles(user)`.
3. Register instance in `arcade/registry.py` with `enabled = True`.
4. Add `templates/arcade/<game_key>.html` + optional `arcade/static/arcade/js/<game_key>.js`.
5. Prefer extending the `PuzzleGame` interface over adding `if game_key ==` branches in views.

---

## 2b. Backyard Marauder is NOT a PuzzleGame — don't force it through the registry

Backyard Marauder (`/arcade/marauder/`) is a real-time shooter, separate from the daily-puzzle machinery. Do **not** register it in `registry.py`, give it a `PuzzleGame` subclass, or route it through `start`/`move`. It owns: `views_marauder.py`, `services_marauder.py`, the `PilotProfile` + `MarauderRun` models, `templates/arcade/marauder*.html`, and `static/arcade/js/marauder/` (ES modules).

- **`MarauderRun.score` is HIGHER-is-better** (opposite of `ArcadeAttempt`). Never compare or aggregate the two. Never copy leaderboard ordering between them.
- Keep the `marauder/*` URL paths **before** the `<game_key>` catch-all in `urls.py`.
- Only `status='valid'` runs count on leaderboards; keep the `idx_marauder_*` indexes if you touch query shape.
- `CHECKSUM_FIELDS` in `services_marauder.py` and the joined array in `net.js::submitRun` must change in the same commit or every submit 403s.
- Constants marked `[SERVER]` in `const.js` must change in the same commit as their mirrors in `services_marauder.py`.
- Do not change the Marauder signing salt without accepting that every in-flight run token dies on deploy.
- Anti-cheat is layered deterrence (salted signed token + token-keyed HMAC + plausibility bounds + unique one-shot seeds). Don't claim it's tamper-proof; the honest hardening path is server-side re-simulation from the run seed.
- Client is vanilla ES modules, no bundler. If you add gameplay randomness, route it through `rng.js` (seeded) so runs stay reproducible.
- Never modify Wordle, Nonogram, or Lights Out code when working on Marauder.
- Any new sprite in `sprites.js` must have every row the same length as `rows[0]`. If the design is meant to be left-right symmetric, every row should be a true palindrome. Verify both with a script before committing (not by eye) — same check used for the Phase 3 enforcer fix.
- Any leaderboard field that renders another user's server-supplied data via `innerHTML` or `insertAdjacentHTML` must go through `escapeHtml()` first. Fields sourced from the *current* player's own local run state are not subject to this rule.
- `game.autoFire` in `main.js` must default to `false`. If a future settings/accessibility feature exposes it as a toggle, gate the default through that setting rather than hardcoding `true` again.

---

## 3. Adding Nonogram Art

Canonical guide: [`docs/ART_AUTHORING.md`](../docs/ART_AUTHORING.md).

Summary: edit `arcade/puzzles/art_pack.py` with a permanent `key` slug, run `python manage.py arcade_verify_art`, commit. Never change a shipped `key`.
