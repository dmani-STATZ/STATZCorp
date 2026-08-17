# Adding Art to the Nonogram Gallery

Everything you need to add a puzzle. Five steps, one command, no Django knowledge required.

---

## TL;DR

1. Open `arcade/puzzles/art_pack.py`
2. Copy an existing block, change the name, key, and grid
3. Run `python manage.py arcade_verify_art`
4. Fix whatever it complains about
5. Commit

The verify command is the gate. If it passes, the puzzle is guaranteed solvable and will show up in the gallery automatically. You never touch views, templates, models, or migrations.

---

## Step 1 — Draw the grid

Grids are plain text. `#` = filled, `.` = empty. One string per row, all rows the same length.

```python
dict(
    key='coffee-mug',          # permanent, lowercase-with-dashes, NEVER change it
    name='Coffee Mug',         # shown to the player after they solve it
    tier='medium',             # easy | medium | hard
    seeds={},                  # leave empty; verify will tell you if you need any
    grid=[
        '..........',
        '.#######..',
        '.#.....#..',
        '.#.....###',
        '.#.....#.#',
        '.#.....###',
        '.#.....#..',
        '.#######..',
        '..#####...',
        '..........',
    ],
),
```

**`key` is permanent.** It's what the gallery uses to remember who solved what. Change a key and everyone loses that piece from their collection. Change the `name`, the `grid`, even the `tier` freely — never the `key`.

Sizes: **5×5** (easy), **10×10** (medium), **15×15** (hard). Stick to these three.

---

## Step 2 — Hit the fill ratio window: 35–55%

This is the one rule that matters, and it's two-sided:

| Fill % | What happens |
|---|---|
| Under 30% | Too ambiguous. Needs seed cells, or fails outright. |
| **35–55%** | **The window. Solvable and readable.** |
| Over 65% | Solver is happy, but it renders as a blob. Nobody can tell what it is. |

The verify command prints the fill % and warns you when you're outside the window. It **cannot** catch the over-65% problem — that's a readability failure, and only your eyes see it. The first Cat drawn for this pack was 74% and looked like a rounded rectangle with notches. Redrawn at 56% with the eyes and mouth as gaps, it reads as a cat instantly.

**The trick for high-density subjects:** don't add detail, *subtract* it. Eyes, mouths, and windows as unfilled gaps inside a solid shape both drop the fill % and make the subject readable.

---

## Step 3 — Draw things that are line-solvable

A nonogram is only fun if it can be solved by pure logic, one row or column at a time, with no guessing. That property comes from **structure**:

**Good:** contiguous runs, symmetry, large solid regions, clean silhouettes.
**Bad:** scattered single pixels, checkerboard texture, noise, fine detail.

Why: a clue like `(6, 2)` on a 10-wide row pins cells down immediately. A clue like `(1, 1, 2, 1, 1)` is nearly free-floating and pins nothing.

This isn't a style preference, it's measurable. Random noise at 15×15 / 45% density is **6% line-solvable**. Hand-drawn art at the same density is **~100%**. Structure is the whole reason authored art works and procedural generation doesn't.

---

## Step 4 — Run verify

```bash
python manage.py arcade_verify_art
```

Output looks like:

```
Coffee Mug     10x10   34% fill   line-solvable   4 passes   OK
Wrench         15x15   25% fill   needs 1 seed               SEEDS
Checkmark       5x5    28% fill   needs 2 seeds              SEEDS
Blobbo         10x10   71% fill   line-solvable   3 passes   WARN: fill > 65%
Broken          9x10    -         -                          FAIL: rows not uniform length
```

Statuses:

- **OK** — done. Ship it.
- **SEEDS** — not solvable as drawn. Verify prints the exact `seeds={...}` dict to paste into your entry. Those cells get pre-revealed when the puzzle loads, which makes it solvable without discarding your art. Paste and re-run.
- **WARN** — solvable, but outside the fill window. Look at it rendered before you trust it.
- **FAIL** — structurally broken. Ragged rows, duplicate key, missing field. Fix and re-run.

Add `--render` to print each grid as blocks so you can eyeball it in the terminal:

```bash
python manage.py arcade_verify_art --render --key coffee-mug
```

**Verify runs in CI.** A FAIL blocks the build, so a broken puzzle can't reach production.

---

## Step 5 — Commit

That's it. The gallery reads the pack directly. New art appears as a locked slot for everyone immediately and enters the daily rotation on its own.

---

## Two things that will surprise you

**Adding art reshuffles the *future* schedule.** The daily puzzle is picked by `days_since_epoch % pack_size`. Grow the pack from 26 to 40 and every future date maps somewhere new. Already-played puzzles are unaffected — each attempt stores its `art_key` at start, so history and everyone's gallery are permanently safe. Only tomorrow onward shifts, and nobody has played tomorrow.

**26 pieces means a 26-day cycle.** Wordle has 1,121 answers and three years of runway. The art pack does not. At 26 pieces people will see repeats inside a month, and a repeat is a free perfect score for anyone who remembers it. **Growing the pack past ~60 is the single highest-value follow-up on this feature.** Two or three pieces a week gets you there painlessly.

---

## Difficulty, if you care

Verify reports **passes** — how many times the line solver had to sweep every row and column before the grid was fully resolved. It's a real difficulty signal, not a guess:

- 2–3 passes — straightforward
- 4–5 passes — needs sustained cross-referencing
- 6+ passes — genuinely hard

Size is a weaker signal than passes. `Light Bulb` at 10×10 takes 6 passes, which makes it harder than three of the four 15×15 pieces in the starter pack. If you want to hand-tune the `tier` field against measured passes rather than grid size, that's a legitimate override — nothing enforces the correlation.
