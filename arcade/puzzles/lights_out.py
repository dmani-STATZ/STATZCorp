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

# Quiet patterns: the GF(2) null space of the 5x5 toggle matrix (dimension 2,
# so 4 cosets -> 4 candidate solutions for any solvable board). Pressing every
# cell of a quiet pattern leaves the board unchanged, so XOR-ing one into a
# solution yields another valid solution of possibly lower weight.
#
#   0x0EAEEAE      0x15A82B5      0x1B06C1B
#    . # # # .      # . # . #      # # . # #
#    # . # . #      # . # . #      . . . . .
#    # # . # #      . . . . .      # # . # #
#    # . # . #      # . # . #      . . . . .
#    . # # # .      # . # . #      # # . # #
#
# Every value must be < 2**25 (the board is 25 cells) and must XOR to zero
# through CELL_TOGGLES. QuietPatternTestCase.test_null_space_masks_are_quiet
# enforces both - do not hand-edit these without rerunning it. A wrong value
# here silently corrupts par for roughly half of all generated puzzles.
NULL_SPACE_MASKS = [0x0000000, 0x0EAEEAE, 0x15A82B5, 0x1B06C1B]

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


def solve_lights_out_solution(grid_mask: int) -> int:
    """
    Return the minimal-weight press set that clears `grid_mask`, as a 25-bit mask.

    Single source of truth for solving. Callers needing only the move count use
    solve_lights_out_par(); tests must call this rather than reimplementing the
    GF(2) math, so a bad constant fails loudly in one place instead of silently
    disagreeing between the game and its tests.

    Precondition: `grid_mask` is reachable by pressing cells from a cleared
    board - which is how generate() builds every puzzle. Only 2**23 of the 2**25
    grid states are solvable at all; passing an unsolvable state returns a mask
    that does not clear the board.
    """
    if grid_mask == 0:
        return 0

    # Particular solution x0 via precomputed GF(2) solver masks
    x0 = 0
    for pc, mask in PIVOT_SOLVER_MASKS:
        if bin(grid_mask & mask).count("1") & 1:
            x0 |= (1 << pc)

    # x0 ^ quiet_pattern is also a solution; keep the one needing fewest presses.
    best = x0
    for ns in NULL_SPACE_MASKS:
        sol = x0 ^ ns
        if bin(sol).count("1") < bin(best).count("1"):
            best = sol
    return best


def solve_lights_out_par(grid_mask: int) -> int:
    """Computes the minimal solution weight (par) for a 5x5 Lights Out grid state over GF(2)."""
    return bin(solve_lights_out_solution(grid_mask)).count("1")


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
