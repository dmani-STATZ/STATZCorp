"""Validate the authored nonogram art pack (verification only — not a request path)."""
from __future__ import annotations

import sys

from django.core.management.base import BaseCommand

from arcade.puzzles.art_pack import ART_PACK, PACK_BY_KEY
from arcade.puzzles.nonogram_solver import classify, min_seeds, solver_passes


FILL_MIN = 35.0
FILL_MAX = 55.0


def _fill_pct(grid) -> float:
    cells = sum(len(r) for r in grid)
    if cells == 0:
        return 0.0
    filled = sum(1 for r in grid for ch in r if ch == "#")
    return 100.0 * filled / cells


def _format_seeds(seeds: dict) -> str:
    if not seeds:
        return "{}"
    parts = []
    for (r, c), v in sorted(seeds.items()):
        parts.append(f"({r}, {c}): {v}")
    return "{" + ", ".join(parts) + "}"


def evaluate_piece(piece: dict) -> dict:
    """Return a status report dict for one pack entry. Used by the command and tests."""
    key = piece.get("key", "?")
    name = piece.get("name", "?")
    grid = piece.get("grid") or []
    seeds = dict(piece.get("seeds") or {})

    result = {
        "key": key,
        "name": name,
        "status": "OK",
        "message": "",
        "nrows": 0,
        "ncols": 0,
        "fill_pct": 0.0,
        "line_solvable": False,
        "passes": 0,
        "suggested_seeds": None,
    }

    if not grid:
        result["status"] = "FAIL"
        result["message"] = "empty grid"
        return result

    row_lens = {len(r) for r in grid}
    if len(row_lens) != 1:
        result["status"] = "FAIL"
        result["message"] = f"rows not uniform length: {sorted(row_lens)}"
        return result

    nrows = len(grid)
    ncols = next(iter(row_lens))
    result["nrows"] = nrows
    result["ncols"] = ncols
    result["fill_pct"] = round(_fill_pct(grid), 1)

    if key not in PACK_BY_KEY or PACK_BY_KEY[key] is not piece and PACK_BY_KEY.get(key, {}).get("key") != key:
        # Soft check — pack already validated at import; still flag missing key.
        if not key or key != key.lower() or " " in key:
            result["status"] = "FAIL"
            result["message"] = "invalid or missing key"
            return result

    for (r, c), val in seeds.items():
        if not (0 <= r < nrows and 0 <= c < ncols):
            result["status"] = "FAIL"
            result["message"] = f"seed {(r, c)} out of bounds"
            return result

    solved_plain, _ = classify(grid)
    solved_with, _ = classify(grid, seeds)

    if solved_plain:
        result["line_solvable"] = True
        result["passes"] = solver_passes(grid)
        fill = result["fill_pct"]
        if fill < FILL_MIN:
            result["status"] = "WARN"
            result["message"] = f"fill < {FILL_MIN:g}% ({fill}%)"
        elif fill > FILL_MAX:
            result["status"] = "WARN"
            result["message"] = f"fill > {FILL_MAX:g}% ({fill}%)"
        else:
            result["status"] = "OK"
        return result

    if solved_with:
        result["line_solvable"] = True
        result["passes"] = solver_passes(grid, seeds)
        # Declared seeds achieve solvability — still report as SEEDS so authors see them,
        # but treat as shippable (not FAIL). Spec: SEEDS = not line-solvable as drawn;
        # print seeds dict. Exit code: FAIL only for structural / insufficient seeds.
        result["status"] = "SEEDS"
        result["message"] = f"needs seeds={_format_seeds(seeds)}"
        result["suggested_seeds"] = seeds
        fill = result["fill_pct"]
        if fill < FILL_MIN or fill > FILL_MAX:
            # Prefer SEEDS over WARN when seeds are required; note fill in message.
            side = "below" if fill < FILL_MIN else "above"
            result["message"] += f" (fill {side} window: {fill}%)"
        return result

    # Not solvable even with declared seeds — try to suggest, then FAIL.
    suggested = min_seeds(grid)
    if suggested is not None:
        # Declared seeds insufficient.
        result["status"] = "FAIL"
        result["message"] = (
            f"declared seeds do not achieve solvability; "
            f"try seeds={_format_seeds(suggested)}"
        )
        result["suggested_seeds"] = suggested
        return result

    result["status"] = "FAIL"
    result["message"] = "not line-solvable; min_seeds could not find a seed set"
    return result


def evaluate_pack(pack=None) -> list[dict]:
    return [evaluate_piece(p) for p in (pack if pack is not None else ART_PACK)]


def _render_grid(grid) -> str:
    lines = []
    for row in grid:
        lines.append("".join("█" if ch == "#" else "·" for ch in row))
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Verify nonogram art pack solvability, fill %, and seed sufficiency."

    def add_arguments(self, parser):
        parser.add_argument(
            "--render",
            action="store_true",
            help="Print grids as block characters.",
        )
        parser.add_argument(
            "--key",
            type=str,
            default="",
            help="Verify a single piece by key slug.",
        )
        parser.add_argument(
            "--fail-on-warn",
            action="store_true",
            help="Exit non-zero on WARN as well as FAIL.",
        )

    def handle(self, *args, **options):
        pack = ART_PACK
        key_filter = (options.get("key") or "").strip()
        if key_filter:
            pack = [p for p in ART_PACK if p["key"] == key_filter]
            if not pack:
                self.stderr.write(self.style.ERROR(f"No piece with key={key_filter!r}"))
                sys.exit(1)

        reports = evaluate_pack(pack)
        has_fail = False
        has_warn = False

        for piece, report in zip(pack, reports):
            dims = f"{report['nrows']}x{report['ncols']}"
            fill = f"{report['fill_pct']}%"
            solv = "line-solvable" if report["line_solvable"] else "not solvable"
            passes = f"{report['passes']} passes" if report["passes"] else "—"
            status = report["status"]
            msg = report["message"]

            line = (
                f"{report['name']:<14} {dims:>5}  {fill:>7} fill  "
                f"{solv:<16} {passes:<12} {status}"
            )
            if msg and status != "OK":
                line += f": {msg}"

            if status == "FAIL":
                has_fail = True
                self.stdout.write(self.style.ERROR(line))
            elif status == "WARN":
                has_warn = True
                self.stdout.write(self.style.WARNING(line))
            elif status == "SEEDS":
                self.stdout.write(self.style.WARNING(line))
                self.stdout.write(f"  paste -> seeds={_format_seeds(report['suggested_seeds'])}")
            else:
                self.stdout.write(self.style.SUCCESS(line))

            if options.get("render"):
                self.stdout.write(_render_grid(piece["grid"]))
                self.stdout.write("")

        if has_fail:
            sys.exit(1)
        if has_warn and options.get("fail_on_warn"):
            sys.exit(1)
