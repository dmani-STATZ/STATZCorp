from datetime import date, timedelta
import zoneinfo
from django.conf import settings
from django.test import SimpleTestCase

from arcade.puzzles.base import derive_seed, rng_for
from arcade.puzzles.lights_out import (
    LightsOutGame,
    solve_lights_out_par,
    NULL_SPACE_MASKS,
    PIVOT_SOLVER_MASKS,
)
from arcade.registry import get_game, get_all_games, get_enabled_games


class PuzzleEngineTestCase(SimpleTestCase):
    def setUp(self):
        self.game = LightsOutGame()

    def test_determinism(self):
        d1 = date(2026, 8, 14)
        puzzle1 = self.game.generate(d1)
        puzzle2 = self.game.generate(d1)
        self.assertEqual(puzzle1, puzzle2)

        p_dates = [d1 + timedelta(days=i) for i in range(3)]
        seeds = [self.game.generate(d)["seed"] for d in p_dates]
        self.assertEqual(len(set(seeds)), 3)

    def test_solvability_200_boards(self):
        start = date(2026, 1, 1)
        for i in range(200):
            d = start + timedelta(days=i)
            puzzle = self.game.generate(d)
            grid = puzzle["initial_grid"]
            grid_mask = sum((grid[r][c] << (r * 5 + c)) for r in range(5) for c in range(5))

            par = solve_lights_out_par(grid_mask)
            self.assertGreater(par, 0)
            self.assertEqual(par, puzzle["par"])

    def test_null_space_dimension(self):
        # 5x5 Lights Out null space has dimension 2 -> exactly 4 solution sets
        self.assertEqual(len(NULL_SPACE_MASKS), 4)

    def test_par_minimality_sample(self):
        start = date(2026, 5, 1)
        for i in range(20):
            d = start + timedelta(days=i)
            puzzle = self.game.generate(d)
            grid = puzzle["initial_grid"]
            grid_mask = sum((grid[r][c] << (r * 5 + c)) for r in range(5) for c in range(5))

            par = puzzle["par"]

            # Particular solution x0 via solver masks
            x0 = 0
            for pc, mask in PIVOT_SOLVER_MASKS:
                if bin(grid_mask & mask).count("1") & 1:
                    x0 |= (1 << pc)

            all_weights = [bin(x0 ^ ns).count("1") for ns in NULL_SPACE_MASKS]
            self.assertEqual(min(all_weights), par)

    def test_payload_redaction(self):
        puzzle = self.game.generate(date(2026, 8, 14))
        state = self.game.initial_state(puzzle)
        payload = self.game.client_payload(puzzle, state)

        self.assertNotIn("par", payload)
        self.assertNotIn("solution", payload)
        self.assertNotIn("null_space", payload)
        self.assertNotIn("seed", payload)
        self.assertNotIn("click_mask", payload)

    def test_registry_all_three_enabled(self):
        all_g = get_all_games()
        self.assertIn("lights_out", all_g)
        self.assertIn("wordle", all_g)
        self.assertIn("nonogram", all_g)

        self.assertTrue(all_g["wordle"].enabled)
        self.assertTrue(all_g["nonogram"].enabled)

        enabled = get_enabled_games()
        self.assertIn("lights_out", enabled)
        self.assertIn("wordle", enabled)
        self.assertIn("nonogram", enabled)

        puzzle = all_g["wordle"].generate(date(2026, 8, 14))
        self.assertIn("answer", puzzle)
        self.assertEqual(len(puzzle["answer"]), 5)

        ng = all_g["nonogram"].generate(date(2026, 8, 14))
        self.assertIn("art_key", ng)
        self.assertIn("row_clues", ng)
        self.assertIsNone(ng.get("par"))
