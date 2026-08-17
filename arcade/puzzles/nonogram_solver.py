"""Nonogram line solver + solvability classifier.

Verification and tests only — never call from request-path views or NonogramGame.
"""
from functools import lru_cache


def derive_clues(grid):
    """grid: list of strings of '#'/'.'  -> (row_clues, col_clues)"""
    rows = []
    for r in grid:
        runs = [len(x) for x in "".join(r).split(".") if x]
        rows.append(tuple(runs) if runs else (0,))
    cols = []
    for c in range(len(grid[0])):
        col = "".join(grid[r][c] for r in range(len(grid)))
        runs = [len(x) for x in col.split(".") if x]
        cols.append(tuple(runs) if runs else (0,))
    return rows, cols


# Bound cache: key space is closed for production use — three grid sizes
# (5/10/15) × the clue tuples present in the authored art pack (and tests).
# Unbounded growth cannot occur from request traffic because the solver is
# never invoked on a request path.
@lru_cache(maxsize=2048)
def placements(length, clues):
    """All binary tuples of given length matching clues. 1=filled, 0=empty."""
    if clues == (0,) or not clues:
        return (tuple([0] * length),)
    out = []

    def rec(pos, idx, acc):
        if idx == len(clues):
            out.append(tuple(acc + [0] * (length - len(acc))))
            return
        need = sum(clues[idx:]) + (len(clues) - idx - 1)
        for start in range(pos, length - need + 1):
            new = acc + [0] * (start - len(acc)) + [1] * clues[idx]
            nxt = start + clues[idx]
            if idx < len(clues) - 1:
                new = new + [0]
                nxt += 1
            if len(new) <= length:
                rec(nxt, idx + 1, new)

    rec(0, 0, [])
    return tuple(out)


UNKNOWN, FILLED, EMPTY = -1, 1, 0


def refine_line(state, clues):
    """Intersect all placements consistent with known state.

    Returns new state list, or None if contradiction (no consistent placement).
    """
    cands = [
        p
        for p in placements(len(state), clues)
        if all(s == UNKNOWN or s == p[i] for i, s in enumerate(state))
    ]
    if not cands:
        return None
    out = []
    for i in range(len(state)):
        vals = {c[i] for c in cands}
        out.append(vals.pop() if len(vals) == 1 else UNKNOWN)
    return out


def line_solve(row_clues, col_clues, nrows, ncols, seeds=None):
    """Iterate line refinement to fixpoint. seeds: {(r,c): val} pre-revealed.

    Returns (grid_state, solved_bool, unknown_count).
    Contradiction (refine_line -> None) yields solved_bool=False, unknown_count=-1.
    """
    g = [[UNKNOWN] * ncols for _ in range(nrows)]
    for (r, c), v in (seeds or {}).items():
        g[r][c] = v
    changed = True
    while changed:
        changed = False
        for r in range(nrows):
            new = refine_line(g[r], row_clues[r])
            if new is None:
                return g, False, -1
            if new != g[r]:
                g[r] = new
                changed = True
        for c in range(ncols):
            col = [g[r][c] for r in range(nrows)]
            new = refine_line(col, col_clues[c])
            if new is None:
                return g, False, -1
            if new != col:
                for r in range(nrows):
                    g[r][c] = new[r]
                changed = True
    unk = sum(1 for r in range(nrows) for c in range(ncols) if g[r][c] == UNKNOWN)
    return g, unk == 0, unk


def solver_passes(grid, seeds=None):
    """Number of full row+column sweeps to fixpoint. Reporting only — does not gate play."""
    rc, cc = derive_clues(grid)
    nrows, ncols = len(grid), len(grid[0])
    g = [[UNKNOWN] * ncols for _ in range(nrows)]
    for (r, c), v in (seeds or {}).items():
        g[r][c] = v
    passes = 0
    changed = True
    while changed:
        changed = False
        passes += 1
        for r in range(nrows):
            new = refine_line(g[r], rc[r])
            if new is None:
                return passes
            if new != g[r]:
                g[r] = new
                changed = True
        for c in range(ncols):
            col = [g[r][c] for r in range(nrows)]
            new = refine_line(col, cc[c])
            if new is None:
                return passes
            if new != col:
                for r in range(nrows):
                    g[r][c] = new[r]
                changed = True
        # Cap runaway (should never hit on authored pack).
        if passes > 10_000:
            break
    return passes


def classify(grid, seeds=None):
    rc, cc = derive_clues(grid)
    nrows, ncols = len(grid), len(grid[0])
    _, solved, unk = line_solve(rc, cc, nrows, ncols, seeds)
    return solved, unk


def min_seeds(grid, cap=12):
    """Greedily add pre-revealed cells until line-solvable. Returns seeds dict or None."""
    rc, cc = derive_clues(grid)
    nrows, ncols = len(grid), len(grid[0])
    truth = {
        (r, c): (FILLED if grid[r][c] == "#" else EMPTY)
        for r in range(nrows)
        for c in range(ncols)
    }
    seeds = {}
    for _ in range(cap):
        g, solved, unk = line_solve(rc, cc, nrows, ncols, seeds)
        if solved:
            return seeds
        best, best_unk = None, 10**9
        cands = [
            (r, c)
            for r in range(nrows)
            for c in range(ncols)
            if g[r][c] == UNKNOWN
        ]
        for (r, c) in cands:
            trial = dict(seeds)
            trial[(r, c)] = truth[(r, c)]
            _, s2, u2 = line_solve(rc, cc, nrows, ncols, trial)
            score = -1 if s2 else u2
            if score < best_unk:
                best_unk, best = score, (r, c)
        if best is None:
            return None
        seeds[best] = truth[best]
    return None
