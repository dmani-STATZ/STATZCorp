from datetime import date, datetime, timedelta
import json
import zoneinfo
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from arcade.models import ArcadeAttempt
from arcade.puzzles.lights_out import (
    LightsOutGame,
    solve_lights_out_par,
    NULL_SPACE_MASKS,
    PIVOT_SOLVER_MASKS,
    CELL_TOGGLES,
)
from arcade.services import compute_handicap, get_arcade_today, make_attempt_token

User = get_user_model()


class ArcadeViewsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="player1",
            password="Password123!",
            first_name="Player",
            last_name="One",
        )
        self.client = Client()

    def test_anonymous_redirect_to_login(self):
        res = self.client.get(reverse("arcade:lobby"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/users/login/", res.url)

    def test_one_attempt_per_user_per_day(self):
        self.client.login(username="player1", password="Password123!")

        res1 = self.client.post(reverse("arcade:start", kwargs={"game_key": "lights_out"}))
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()

        res2 = self.client.post(reverse("arcade:start", kwargs={"game_key": "lights_out"}))
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()

        self.assertEqual(data1["attempt_id"], data2["attempt_id"])
        self.assertEqual(
            ArcadeAttempt.objects.filter(user=self.user, game_key="lights_out").count(), 1
        )

    def test_grading_optimal_and_redundant_moves(self):
        self.client.login(username="player1", password="Password123!")

        res_start = self.client.post(reverse("arcade:start", kwargs={"game_key": "lights_out"}))
        data_start = res_start.json()
        attempt_id = data_start["attempt_id"]
        token = data_start["token"]

        attempt = ArcadeAttempt.objects.get(pk=attempt_id)
        game = LightsOutGame()
        puzzle = game.generate(attempt.puzzle_date)

        grid = puzzle["initial_grid"]
        grid_mask = sum((grid[r][c] << (r * 5 + c)) for r in range(5) for c in range(5))

        # Solve via fast PIVOT_SOLVER_MASKS
        x0 = 0
        for pc, mask in PIVOT_SOLVER_MASKS:
            if bin(grid_mask & mask).count("1") & 1:
                x0 |= (1 << pc)

        # Pick minimal solution (par)
        best_sol = None
        min_w = 25
        for ns in NULL_SPACE_MASKS:
            sol = x0 ^ ns
            w = bin(sol).count("1")
            if w < min_w:
                min_w = w
                best_sol = sol

        # Convert solution bitmask into coordinate moves
        moves_list = []
        for i in range(25):
            if (best_sol >> i) & 1:
                moves_list.append((i // 5, i % 5))

        # Play all optimal moves except the last one
        for r, c in moves_list[:-1]:
            res_move = self.client.post(
                reverse("arcade:move", kwargs={"game_key": "lights_out"}),
                data=json.dumps({
                    "attempt_id": attempt_id,
                    "token": token,
                    "move": {"row": r, "col": c},
                }),
                content_type="application/json",
            )
            self.assertEqual(res_move.status_code, 200)

        # Make final move
        last_r, last_c = moves_list[-1]
        res_final = self.client.post(
            reverse("arcade:move", kwargs={"game_key": "lights_out"}),
            data=json.dumps({
                "attempt_id": attempt_id,
                "token": token,
                "move": {"row": last_r, "col": last_c},
            }),
            content_type="application/json",
        )
        data_final = res_final.json()
        self.assertEqual(data_final["attempt_status"], "solved")
        self.assertEqual(data_final["score"], 0)

    def test_idle_cap(self):
        self.client.login(username="player1", password="Password123!")

        res_start = self.client.post(reverse("arcade:start", kwargs={"game_key": "lights_out"}))
        data_start = res_start.json()
        attempt_id = data_start["attempt_id"]
        token = data_start["token"]

        attempt = ArcadeAttempt.objects.get(pk=attempt_id)
        # Simulate started_at 10 minutes (600,000ms) ago
        ten_mins_ago = timezone.now() - timedelta(minutes=10)
        attempt.started_at = ten_mins_ago
        attempt.save()

        res_move = self.client.post(
            reverse("arcade:move", kwargs={"game_key": "lights_out"}),
            data=json.dumps({
                "attempt_id": attempt_id,
                "token": token,
                "move": {"row": 0, "col": 0},
            }),
            content_type="application/json",
        )
        data_move = res_move.json()
        self.assertEqual(data_move["active_ms"], 120000)

    def test_handicap_calculation_and_suppression(self):
        # Handicap is suppressed when qualifying count < 5
        h_info = compute_handicap(self.user, "lights_out")
        self.assertIsNone(h_info["handicap"])
        self.assertEqual(h_info["display"], "5 more to qualify")

        # Create 5 completed attempts (3 solved with score=0, 2 abandoned)
        today = get_arcade_today()
        for i in range(3):
            ArcadeAttempt.objects.create(
                user=self.user,
                game_key="lights_out",
                puzzle_date=today - timedelta(days=i + 1),
                seed="seed",
                par=8,
                moves_used=8,
                score=0,
                status=ArcadeAttempt.STATUS_SOLVED,
                started_at=timezone.now(),
            )
        for i in range(2):
            ArcadeAttempt.objects.create(
                user=self.user,
                game_key="lights_out",
                puzzle_date=today - timedelta(days=i + 4),
                seed="seed",
                par=8,
                moves_used=0,
                score=None,
                status=ArcadeAttempt.STATUS_ABANDONED,
                started_at=timezone.now(),
            )

        # 3 solved @ 0, 2 abandoned @ 10 -> sum = 20, count = 5 -> average = 4.0
        h_info5 = compute_handicap(self.user, "lights_out")
        self.assertEqual(h_info5["handicap"], 4.0)
        self.assertEqual(h_info5["display"], "+4.0")

    def test_day_boundary_uses_local_time_zone(self):
        tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        local_today = timezone.now().astimezone(tz).date()
        self.assertEqual(get_arcade_today(), local_today)
