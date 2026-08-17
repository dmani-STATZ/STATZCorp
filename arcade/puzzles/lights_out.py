from datetime import date
import logging
from .base import PuzzleGame, derive_seed, rng_for

logger = logging.getLogger(__name__)

# Precompute 5x5 toggle masks for each cell (0..24)
CELL_TOGGLES = []
for r in range(5):
    for c in range(5):
        mask = 0
        for dr, dc in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < 5 and 0 <= nc < 5:
                mask |= (1 << (nr * 5 + nc))
        CELL_TOGGLES.append(mask)

# Null space coset masks over GF(2) (dimension 2 -> 4 solution sets per board)
NULL_SPACE_MASKS = [0, 0x00EAEAEA, 0x015A005A5, 0x01B03603B]

# Precomputed solver masks for pivot columns over GF(2)
# Allows O(1) solving (~1 microsecond) without running matrix elimination per call.
PIVOT_SOLVER_MASKS = (
    (0, 549518), (1, 290907), (2, 3125693), (3, 7405639), (4, 3822646),
    (5, 791252), (6, 2335594), (7, 5947813), (8, 6612420), (9, 4936801),
    (10, 2609936), (11, 7405568), (12, 3290678), (13, 291143), (14, 1435539),
    (15, 5948868), (16, 4673100), (17, 1939156), (18, 4678950), (19, 5931701),
    (20, 3856536), (21, 7347548), (22, 2984840)
)

# Weekday difficulty target par bands: (min_par, max_par)
# 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
WEEKDAY_PAR_BANDS = {
    0: (6, 7),
    1: (8, 8),
    2: (9, 9),
    3: (10, 10),
    4: (11, 11),
    5: (12, 13),
    6: (9, 10),
}


def solve_lights_out_par(grid_mask: int) -> int:
    """Computes the minimal solution weight (par) for a 5x5 Lights Out grid state over GF(2)."""
    if grid_mask == 0:
        return 0

    # Particular solution x0 via precomputed GF(2) solver masks
    x0 = 0
    for pc, mask in PIVOT_SOLVER_MASKS:
        if bin(grid_mask & mask).count("1") & 1:
            x0 |= (1 << pc)

    # Find minimum popcount across all 4 nullspace coset solutions
    min_par = 25
    for ns in NULL_SPACE_MASKS:
        sol = x0 ^ ns
        w = bin(sol).count("1")
        if w < min_par:
            min_par = w
    return min_par


class LightsOutGame(PuzzleGame):
    game_key = "lights_out"
    display_name = "Lights Out"
    enabled = True
    blurb = "Toggle lights to turn the entire grid off. Neighboring lights flip with every click."
    score_label = "over par"
    stale_score = 10

    def format_score(self, value, attempt=None) -> str:
        if value is None:
            return "—"
        if value > 0:
            return f"+{value} over par"
        if value == 0:
            return "Par (0)"
        return f"{value} over par"

    def score_on_complete(self, puzzle: dict, state: dict) -> int:
        return int(state.get("moves_used", 0)) - int(puzzle["par"])

    def generate(self, puzzle_date: date) -> dict:
        seed_hex = derive_seed(self.game_key, puzzle_date)
        rng = rng_for(seed_hex)

        target_min, target_max = WEEKDAY_PAR_BANDS.get(puzzle_date.weekday(), (9, 10))

        accepted_grid = None
        accepted_par = None
        curr_min, curr_max = target_min, target_max

        for attempts in range(1, 501):
            click_mask = rng.randint(1, (1 << 25) - 1)
            grid_mask = 0
            for i in range(25):
                if (click_mask >> i) & 1:
                    grid_mask ^= CELL_TOGGLES[i]

            if grid_mask == 0:
                continue

            par = solve_lights_out_par(grid_mask)
            if par == 0:
                continue

            if curr_min <= par <= curr_max:
                accepted_grid = grid_mask
                accepted_par = par
                break

            if attempts == 500:
                logger.warning(
                    "Lights Out generation cap (500) reached for date %s. Par was %d. Accepting board.",
                    puzzle_date,
                    par,
                )
                accepted_grid = grid_mask
                accepted_par = par

        # Convert 25-bit integer grid_mask into 5x5 2D array of 0s and 1s
        initial_grid = [
            [(accepted_grid >> (r * 5 + c)) & 1 for c in range(5)]
            for r in range(5)
        ]

        return {
            "game_key": self.game_key,
            "puzzle_date": puzzle_date.isoformat(),
            "seed": seed_hex,
            "par": accepted_par,
            "initial_grid": initial_grid,
        }

    def initial_state(self, puzzle: dict) -> dict:
        return {
            "grid": [row[:] for row in puzzle["initial_grid"]],
            "moves_used": 0,
            "last_move_at": None,
        }

    def apply_move(self, puzzle: dict, state: dict, move: dict) -> dict:
        row = move.get("row")
        col = move.get("col")
        if row is None or col is None or not (0 <= row < 5 and 0 <= col < 5):
            raise ValueError("Invalid move coordinates: row and col must be between 0 and 4.")

        grid = [r[:] for r in state["grid"]]
        for dr, dc in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = row + dr, col + dc
            if 0 <= nr < 5 and 0 <= nc < 5:
                grid[nr][nc] ^= 1

        new_state = dict(state)
        new_state["grid"] = grid
        new_state["moves_used"] = state.get("moves_used", 0) + 1
        return new_state

    def is_solved(self, puzzle: dict, state: dict) -> bool:
        return all(cell == 0 for row in state["grid"] for cell in row)

    def client_payload(self, puzzle: dict, state: dict) -> dict:
        return {
            "game_key": self.game_key,
            "grid": state["grid"],
            "moves_used": state.get("moves_used", 0),
            "is_solved": self.is_solved(puzzle, state),
        }
