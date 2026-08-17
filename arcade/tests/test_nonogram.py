"""Nonogram pack integrity, gameplay, scoring, gallery, and isolation tests."""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from arcade.management.commands.arcade_verify_art import evaluate_pack
from arcade.models import ArcadeAttempt
from arcade.puzzles.art_pack import ART_PACK, PACK_BY_KEY, pack_load_count
from arcade.puzzles.base import MoveRejected
from arcade.puzzles.nonogram import NonogramGame, art_for, _ART_ORDER
from arcade.puzzles.nonogram_solver import classify, line_solve
from arcade.services import compute_handicap, get_arcade_today

User = get_user_model()


class PackIntegrityTestCase(SimpleTestCase):
    def test_uniform_keys_tiers_seeds(self):
        keys = set()
        for piece in ART_PACK:
            self.assertEqual(len({len(r) for r in piece["grid"]}), 1)
            self.assertEqual(len(piece["grid"]), len(piece["grid"][0]))
            self.assertIn(piece["tier"], {"easy", "medium", "hard"})
            self.assertNotIn(piece["key"], keys)
            keys.add(piece["key"])
            nrows, ncols = len(piece["grid"]), len(piece["grid"][0])
            for (r, c), v in (piece.get("seeds") or {}).items():
                self.assertTrue(0 <= r < nrows and 0 <= c < ncols)
                self.assertIn(v, (0, 1))

    def test_every_piece_line_solvable_with_declared_seeds(self):
        for piece in ART_PACK:
            with self.subTest(key=piece["key"]):
                solved, _ = classify(piece["grid"], piece.get("seeds") or {})
                self.assertTrue(
                    solved,
                    msg=f"{piece['key']} not line-solvable with declared seeds",
                )

    def test_pack_loads_once(self):
        self.assertEqual(pack_load_count(), 1)

    def test_verify_zero_fail(self):
        reports = evaluate_pack()
        fails = [r for r in reports if r["status"] == "FAIL"]
        self.assertEqual(fails, [], msg=fails)


class SelectionTestCase(SimpleTestCase):
    def test_same_date_same_art(self):
        d = date(2026, 3, 15)
        self.assertEqual(art_for(d)["key"], art_for(d)["key"])

    def test_full_pack_no_repeats_then_wraps(self):
        epoch = settings.ARCADE_NONOGRAM_EPOCH
        n = len(_ART_ORDER)
        self.assertEqual(n, len(ART_PACK))
        seen = [art_for(epoch + timedelta(days=i))["key"] for i in range(n)]
        self.assertEqual(len(set(seen)), n)
        self.assertEqual(
            art_for(epoch + timedelta(days=n))["key"],
            art_for(epoch)["key"],
        )

    def test_date_before_epoch_returns_valid_art(self):
        before = settings.ARCADE_NONOGRAM_EPOCH - timedelta(days=1)
        art = art_for(before)
        self.assertIn(art["key"], PACK_BY_KEY)


class MoveAndScoreTestCase(SimpleTestCase):
    def setUp(self):
        self.game = NonogramGame()
        # Use Plus — simple 5x5, no seeds.
        self.puzzle = self.game.generate(date(2026, 1, 2))
        # Force known art for deterministic cells if needed
        from arcade.puzzles.art_pack import PACK_BY_KEY as P

        self.plus = P["plus"]
        self.puzzle = {
            **self.puzzle,
            "art_key": "plus",
            "grid": self.plus["grid"],
            "seeds": {},
            "name": "Plus",
            "nrows": 5,
            "ncols": 5,
        }
        self.state = self.game.initial_state(self.puzzle)

    def test_correct_fill(self):
        # Plus has center cross — (0,2) is filled
        state = self.game.apply_move(
            self.puzzle, self.state, {"action": "fill", "row": 0, "col": 2}
        )
        self.assertEqual(state["last_result"], "correct")
        self.assertEqual(state["mistakes"], 0)
        self.assertIn([0, 2], state["filled"])

    def test_wrong_fill_auto_marks(self):
        state = self.game.apply_move(
            self.puzzle, self.state, {"action": "fill", "row": 0, "col": 0}
        )
        self.assertEqual(state["last_result"], "mistake")
        self.assertEqual(state["mistakes"], 1)
        self.assertIn([0, 0], state["marked"])

    def test_refill_already_filled_no_op(self):
        state = self.game.apply_move(
            self.puzzle, self.state, {"action": "fill", "row": 0, "col": 2}
        )
        with self.assertRaises(MoveRejected) as ctx:
            self.game.apply_move(
                self.puzzle, state, {"action": "fill", "row": 0, "col": 2}
            )
        self.assertEqual(ctx.exception.reason, "already_filled")
        self.assertEqual(state["mistakes"], 0)
        self.assertEqual(len(state["filled"]), 1)

    def test_fill_already_marked_no_mistake(self):
        state = self.game.apply_move(
            self.puzzle, self.state, {"action": "mark", "row": 0, "col": 0}
        )
        mistakes = state["mistakes"]
        with self.assertRaises(MoveRejected) as ctx:
            self.game.apply_move(
                self.puzzle, state, {"action": "fill", "row": 0, "col": 0}
            )
        self.assertEqual(ctx.exception.reason, "already_marked")
        self.assertEqual(state["mistakes"], mistakes)

    def test_mark_never_changes_mistakes_and_toggles(self):
        state = self.game.apply_move(
            self.puzzle, self.state, {"action": "mark", "row": 1, "col": 1}
        )
        self.assertEqual(state["mistakes"], 0)
        self.assertIn([1, 1], state["marked"])
        state = self.game.apply_move(
            self.puzzle, state, {"action": "mark", "row": 1, "col": 1}
        )
        self.assertEqual(state["mistakes"], 0)
        self.assertNotIn([1, 1], state["marked"])

    def test_scoring_free_misses_and_penalty(self):
        for mistakes, expected_penalty in [(0, 0), (1, 0), (2, 0), (3, 30), (5, 90)]:
            state = {"active_ms": 0, "mistakes": mistakes}
            score = self.game.score_on_complete(self.puzzle, state)
            self.assertEqual(score, expected_penalty, msg=f"mistakes={mistakes}")

        state = {"active_ms": 240_000, "mistakes": 4}
        self.assertEqual(self.game.score_on_complete(self.puzzle, state), 300)

    def test_format_score_with_miss_suffix(self):
        self.assertEqual(self.game.format_score(252), "4:12")

        class FakeAttempt:
            def get_state(self):
                return {"mistakes": 4}

        self.assertEqual(
            self.game.format_score(300, attempt=FakeAttempt()),
            "5:00 (+2 misses)",
        )

    def test_payload_redaction(self):
        state = self.state
        # Several moves while in progress
        for r, c in [(0, 0), (0, 2), (1, 2)]:
            try:
                state = self.game.apply_move(
                    self.puzzle, state, {"action": "fill", "row": r, "col": c}
                )
            except Exception:
                pass
            payload = self.game.client_payload(self.puzzle, state)
            if not payload["is_solved"]:
                self.assertNotIn("grid", payload)
                self.assertNotIn("art_key", payload)
                self.assertNotIn("name", payload)

        # Solve completely
        state = self.game.initial_state(self.puzzle)
        grid = self.plus["grid"]
        for r, row in enumerate(grid):
            for c, ch in enumerate(row):
                if ch == "#":
                    state = self.game.apply_move(
                        self.puzzle, state, {"action": "fill", "row": r, "col": c}
                    )
        self.assertTrue(self.game.is_solved(self.puzzle, state))
        payload = self.game.client_payload(self.puzzle, state)
        self.assertIn("name", payload)
        self.assertIn("grid", payload)


class PackGrowthImmutabilityTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ng_player", password="Password123!"
        )
        self.game = NonogramGame()

    def test_pack_growth_does_not_change_in_progress_or_gallery(self):
        today = get_arcade_today()
        puzzle = self.game.generate(today)
        state = self.game.initial_state(puzzle)
        original_key = state["art_key"]
        original_grid = list(PACK_BY_KEY[original_key]["grid"])

        attempt = ArcadeAttempt.objects.create(
            user=self.user,
            game_key="nonogram",
            puzzle_date=today,
            seed=puzzle["seed"],
            status=ArcadeAttempt.STATUS_IN_PROGRESS,
            started_at=timezone.now(),
        )
        attempt.set_state(state)
        attempt.save()

        # Append synthetic piece (simulates pack growth).
        synthetic = {
            "key": "zz-synthetic-test-only",
            "name": "Synthetic",
            "size": 5,
            "tier": "easy",
            "passes": 1,
            "seeds": {},
            "grid": [
                "#####",
                "#...#",
                "#...#",
                "#...#",
                "#####",
            ],
        }
        ART_PACK.append(synthetic)
        PACK_BY_KEY[synthetic["key"]] = synthetic
        try:
            # Date-based selection may now differ, but grading uses art_key.
            wrong_puzzle = self.game.generate(today)
            # Even if generate returns a different art_key for the date, apply_move
            # must grade against the persisted key.
            attempt_state = attempt.get_state()
            self.assertEqual(attempt_state["art_key"], original_key)

            # Correct fill on original art still works.
            # Find a fillable empty cell on original.
            filled = {(0, 0)}  # may or may not be correct — use a known # cell
            r = c = None
            for rr, row in enumerate(original_grid):
                for cc, ch in enumerate(row):
                    if ch == "#":
                        r, c = rr, cc
                        break
                if r is not None:
                    break
            new_state = self.game.apply_move(
                wrong_puzzle, attempt_state, {"action": "fill", "row": r, "col": c}
            )
            self.assertEqual(new_state["art_key"], original_key)
            self.assertEqual(new_state["last_result"], "correct")

            # Gallery unlock uses persisted art_key on solved attempts.
            attempt.status = ArcadeAttempt.STATUS_SOLVED
            attempt.completed_at = timezone.now()
            attempt.score = 10
            attempt.set_state(new_state)
            attempt.save()

            gallery = self.game.gallery_tiles(self.user)
            unlocked_keys = {
                t["key"] for t in gallery["tiles"] if t.get("unlocked")
            }
            self.assertIn(original_key, unlocked_keys)
            self.assertNotIn("zz-synthetic-test-only", unlocked_keys)
        finally:
            ART_PACK.pop()
            PACK_BY_KEY.pop(synthetic["key"], None)


class IdleCapAndViewsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ng_view", password="Password123!"
        )
        self.client = Client()
        self.client.login(username="ng_view", password="Password123!")
        self.game = NonogramGame()

    def _start(self):
        res = self.client.post(reverse("arcade:start", kwargs={"game_key": "nonogram"}))
        self.assertEqual(res.status_code, 200)
        return res.json()

    def _move(self, attempt_id, token, action, row, col):
        return self.client.post(
            reverse("arcade:move", kwargs={"game_key": "nonogram"}),
            data=json.dumps({
                "attempt_id": attempt_id,
                "token": token,
                "move": {"action": action, "row": row, "col": col},
            }),
            content_type="application/json",
        )

    def test_idle_cap_between_moves(self):
        data = self._start()
        attempt = ArcadeAttempt.objects.get(pk=data["attempt_id"])
        puzzle = self.game.generate(attempt.puzzle_date)
        # Force last_move via started_at 10 minutes ago on first move
        ten_mins_ago = timezone.now() - timedelta(minutes=10)
        attempt.started_at = ten_mins_ago
        attempt.save()

        # Pick any empty cell for a mark (free)
        res = self._move(data["attempt_id"], data["token"], "mark", 0, 0)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["active_ms"], 120000)

    def test_line_solve_not_invoked_by_views(self):
        with mock.patch(
            "arcade.puzzles.nonogram_solver.line_solve", wraps=line_solve
        ) as mocked:
            # Also patch where it would be looked up if imported — ensure nonogram module path
            with mock.patch(
                "arcade.puzzles.nonogram.line_solve", create=True
            ) as ng_mock:
                data = self._start()
                self._move(data["attempt_id"], data["token"], "mark", 0, 0)
                self.client.get(
                    reverse("arcade:gallery", kwargs={"game_key": "nonogram"})
                )
                self.client.get(
                    reverse("arcade:play", kwargs={"game_key": "nonogram"})
                )
                mocked.assert_not_called()
                ng_mock.assert_not_called()

    def test_gallery_locked_tiles_leak_nothing(self):
        res = self.client.get(
            reverse("arcade:gallery", kwargs={"game_key": "nonogram"})
        )
        self.assertEqual(res.status_code, 200)
        # No piece names from pack in locked-only gallery for new user
        for piece in ART_PACK:
            self.assertNotContains(res, piece["name"])

    def test_gallery_unlocks_solved_only(self):
        today = get_arcade_today()
        keys = [ART_PACK[i]["key"] for i in range(3)]
        for i, key in enumerate(keys):
            att = ArcadeAttempt.objects.create(
                user=self.user,
                game_key="nonogram",
                puzzle_date=today - timedelta(days=i + 1),
                seed="seed",
                status=ArcadeAttempt.STATUS_SOLVED,
                score=100,
                started_at=timezone.now(),
                completed_at=timezone.now(),
            )
            att.set_state({"art_key": key, "mistakes": 0, "filled": [], "marked": []})
            att.save()

        # In-progress does not unlock
        prog = ArcadeAttempt.objects.create(
            user=self.user,
            game_key="nonogram",
            puzzle_date=today,
            seed="seed",
            status=ArcadeAttempt.STATUS_IN_PROGRESS,
            started_at=timezone.now(),
        )
        prog.set_state({"art_key": ART_PACK[5]["key"], "mistakes": 0})
        prog.save()

        gallery = self.game.gallery_tiles(self.user)
        self.assertEqual(gallery["collected"], 3)
        unlocked = [t for t in gallery["tiles"] if t.get("unlocked")]
        self.assertEqual(len(unlocked), 3)
        for t in gallery["tiles"]:
            if not t.get("unlocked"):
                self.assertEqual(set(t.keys()), {"unlocked"})

    def test_handicap_mixed_games(self):
        today = get_arcade_today()
        for i in range(5):
            ArcadeAttempt.objects.create(
                user=self.user,
                game_key="nonogram",
                puzzle_date=today - timedelta(days=i + 1),
                seed="s",
                status=ArcadeAttempt.STATUS_SOLVED,
                score=100 + i,
                started_at=timezone.now(),
                completed_at=timezone.now(),
            )
        h = compute_handicap(self.user, "nonogram")
        self.assertIsNotNone(h["handicap"])


class RegressionEnabledTestCase(SimpleTestCase):
    def test_nonogram_enabled_in_registry(self):
        from arcade.registry import get_game, get_enabled_games

        g = get_game("nonogram")
        self.assertTrue(g.enabled)
        self.assertIn("nonogram", get_enabled_games())
