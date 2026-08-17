"""Nonogram daily puzzle — authored art only, server-authoritative grading.

Clues fully determine the solution (true of every nonogram and of Lights Out).
A determined player could run an external solver; that is not a defect and needs
no mitigation. This module never imports or calls the line solver on a request path.
"""
from __future__ import annotations

import random
from datetime import date

from django.conf import settings

from .art_pack import ART_PACK, PACK_BY_KEY
from .base import MoveRejected, PuzzleGame, derive_seed
from .nonogram_solver import EMPTY, FILLED, derive_clues


def _build_order() -> tuple[str, ...]:
    """Stable shuffled pack keys. Dedicated RNG; never the global random module."""
    epoch = settings.ARCADE_NONOGRAM_EPOCH
    keys = [p["key"] for p in ART_PACK]
    seed_hex = derive_seed("nonogram_order", epoch)
    random.Random(int(seed_hex[:16], 16)).shuffle(keys)
    return tuple(keys)


# Computed once at import — never reshuffled per request.
_ART_ORDER: tuple[str, ...] = _build_order()


def _shuffled_keys() -> tuple[str, ...]:
    """Single-function switch point if weekday/tier scheduling is added later."""
    return _ART_ORDER


def art_for(puzzle_date: date) -> dict:
    """Flat rotation by days since epoch. Pack growth remaps future dates only."""
    order = _shuffled_keys()
    epoch = settings.ARCADE_NONOGRAM_EPOCH
    idx = (puzzle_date - epoch).days % len(order)
    return PACK_BY_KEY[order[idx]]


def _cell_set(pairs) -> set[tuple[int, int]]:
    out = set()
    for item in pairs or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.add((int(item[0]), int(item[1])))
    return out


def _cell_list(cells: set[tuple[int, int]]) -> list[list[int]]:
    return [[r, c] for r, c in sorted(cells)]


def _resolve_art(puzzle: dict, state: dict) -> dict:
    """ALWAYS prefer art_key persisted on the attempt.

    Pack growth changes len(order) and remaps art_for(date). Grading and gallery
    must never recompute from puzzle_date alone.
    """
    key = (state or {}).get("art_key") or puzzle.get("art_key")
    if not key or key not in PACK_BY_KEY:
        raise MoveRejected("invalid_art", "Puzzle art is unavailable.", http_status=500)
    return PACK_BY_KEY[key]


def _should_fill(art: dict, row: int, col: int) -> bool:
    return art["grid"][row][col] == "#"


class NonogramGame(PuzzleGame):
    game_key = "nonogram"
    display_name = "Nonogram"
    enabled = True
    blurb = "Picture logic puzzle. Fill cells from the row and column clues."
    score_label = "time"
    stale_score = 600  # 10 minutes of adjusted time — harsh but finite
    has_gallery = True

    def format_score(self, value, attempt=None) -> str:
        if value is None:
            return "—"
        total_sec = int(value)
        mins = total_sec // 60
        secs = total_sec % 60
        base = f"{mins}:{secs:02d}"
        if attempt is not None:
            mistakes = int(attempt.get_state().get("mistakes") or 0)
            penalty = max(0, mistakes - 2)
            if penalty:
                return f"{base} (+{penalty} misses)"
        return base

    def detail(self, state: dict) -> str:
        mistakes = int((state or {}).get("mistakes") or 0)
        if mistakes <= 0:
            return ""
        unit = "miss" if mistakes == 1 else "misses"
        return f"{mistakes} {unit}"

    def generate(self, puzzle_date: date) -> dict:
        # art_for is the ONLY place that maps a date → art. apply_move / gallery
        # read persisted art_key instead.
        art = art_for(puzzle_date)
        grid = art["grid"]
        row_clues, col_clues = derive_clues(grid)
        seed_hex = derive_seed(self.game_key, puzzle_date)
        seeds = {
            (int(r), int(c)): int(v) for (r, c), v in (art.get("seeds") or {}).items()
        }
        return {
            "game_key": self.game_key,
            "puzzle_date": puzzle_date.isoformat(),
            "seed": seed_hex,
            "par": None,
            "art_key": art["key"],
            "name": art["name"],
            "grid": list(grid),
            "row_clues": [list(c) for c in row_clues],
            "col_clues": [list(c) for c in col_clues],
            "seeds": seeds,
            "nrows": len(grid),
            "ncols": len(grid[0]),
        }

    def initial_state(self, puzzle: dict) -> dict:
        filled: set[tuple[int, int]] = set()
        marked: set[tuple[int, int]] = set()
        for (r, c), val in (puzzle.get("seeds") or {}).items():
            if val == FILLED:
                filled.add((r, c))
            elif val == EMPTY:
                marked.add((r, c))
        return {
            "filled": _cell_list(filled),
            "marked": _cell_list(marked),
            "mistakes": 0,
            "art_key": puzzle["art_key"],
            "moves_used": 0,
            "last_move_at": None,
            "last_result": None,
        }

    def apply_move(self, puzzle: dict, state: dict, move: dict) -> dict:
        art = _resolve_art(puzzle, state)
        nrows = len(art["grid"])
        ncols = len(art["grid"][0])

        if not isinstance(move, dict):
            raise MoveRejected("malformed", "Move must be an object.")

        action = move.get("action")
        if action not in ("fill", "mark"):
            raise MoveRejected("malformed", "action must be 'fill' or 'mark'.")

        try:
            row = int(move["row"])
            col = int(move["col"])
        except (KeyError, TypeError, ValueError):
            raise MoveRejected("malformed", "row and col must be integers.") from None

        if not (0 <= row < nrows and 0 <= col < ncols):
            raise MoveRejected("out_of_bounds", "Cell is outside the grid.")

        filled = _cell_set(state.get("filled"))
        marked = _cell_set(state.get("marked"))
        mistakes = int(state.get("mistakes") or 0)
        moves_used = int(state.get("moves_used") or 0)
        cell = (row, col)
        last_result = None

        if action == "mark":
            if cell in filled:
                raise MoveRejected("already_filled", "Cell is already filled.")
            if cell in marked:
                marked.discard(cell)
            else:
                marked.add(cell)
        else:  # fill
            if cell in filled:
                raise MoveRejected("already_filled", "Cell is already filled.")
            if cell in marked:
                raise MoveRejected("already_marked", "Cell is already marked empty.")
            if _should_fill(art, row, col):
                filled.add(cell)
                last_result = "correct"
            else:
                mistakes += 1
                marked.add(cell)
                last_result = "mistake"
            moves_used += 1

        return {
            "filled": _cell_list(filled),
            "marked": _cell_list(marked),
            "mistakes": mistakes,
            "art_key": state.get("art_key") or puzzle["art_key"],
            "moves_used": moves_used,
            "last_move_at": state.get("last_move_at"),
            "last_result": last_result,
            "active_ms": state.get("active_ms"),
        }

    def is_solved(self, puzzle: dict, state: dict) -> bool:
        art = _resolve_art(puzzle, state)
        filled = _cell_set(state.get("filled"))
        for r, row in enumerate(art["grid"]):
            for c, ch in enumerate(row):
                if ch == "#" and (r, c) not in filled:
                    return False
        return True

    def is_failed(self, puzzle: dict, state: dict) -> bool:
        return False

    def score_on_complete(self, puzzle: dict, state: dict) -> int:
        active_ms = int(state.get("active_ms") or 0)
        mistakes = int(state.get("mistakes") or 0)
        return round(active_ms / 1000) + max(0, mistakes - 2) * 30

    def client_payload(self, puzzle: dict, state: dict) -> dict:
        art = _resolve_art(puzzle, state)
        grid = art["grid"]
        row_clues, col_clues = derive_clues(grid)
        mistakes = int(state.get("mistakes") or 0)
        solved = self.is_solved(puzzle, state)
        payload = {
            "game_key": self.game_key,
            "nrows": len(grid),
            "ncols": len(grid[0]),
            "row_clues": [list(c) for c in row_clues],
            "col_clues": [list(c) for c in col_clues],
            "filled": list(state.get("filled") or []),
            "marked": list(state.get("marked") or []),
            "mistakes": mistakes,
            "free_misses_left": max(0, 2 - mistakes),
            "result": state.get("last_result"),
            "is_solved": solved,
        }
        if solved:
            payload["name"] = art["name"]
            payload["grid"] = list(grid)
        return payload

    def gallery_tiles(self, user) -> dict:
        """Build gallery context. Unlocks from persisted art_key on solved attempts."""
        from arcade.models import ArcadeAttempt

        attempts = list(
            ArcadeAttempt.objects.filter(
                user=user,
                game_key=self.game_key,
                status=ArcadeAttempt.STATUS_SOLVED,
            )
        )
        unlocked: dict[str, dict] = {}
        for att in attempts:
            key = att.get_state().get("art_key")
            if not key or key not in PACK_BY_KEY:
                continue
            prev = unlocked.get(key)
            if prev is None or (
                att.completed_at
                and prev.get("solved_at")
                and att.completed_at < prev["solved_at"]
            ):
                unlocked[key] = {
                    "solved_at": att.completed_at,
                    "puzzle_date": att.puzzle_date,
                }

        tiles = []
        for piece in ART_PACK:
            key = piece["key"]
            info = unlocked.get(key)
            if info:
                tiles.append({
                    "unlocked": True,
                    "key": key,
                    "name": piece["name"],
                    "grid": piece["grid"],
                    "solved_at": info["solved_at"],
                    "puzzle_date": info["puzzle_date"],
                })
            else:
                tiles.append({"unlocked": False})

        return {
            "tiles": tiles,
            "collected": len(unlocked),
            "total": len(ART_PACK),
        }
