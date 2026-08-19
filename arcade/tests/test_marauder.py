import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse, resolve
from django.utils import timezone

from arcade.models import PilotProfile, MarauderRun
from arcade.services_marauder import (
    compute_run_checksum,
    make_run_token,
    verify_run_token,
    get_global_top,
    get_user_top,
)

User = get_user_model()


class MarauderTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pilot1", password="Password123!", first_name="Ace", last_name="Pilot"
        )
        self.client = Client()
        self.client.login(username="pilot1", password="Password123!")

    def _start(self):
        res = self.client.post(reverse("arcade:marauder_start"))
        self.assertEqual(res.status_code, 200)
        return res.json()

    def _payload(self, start, **overrides):
        stats = {
            "seed": start["seed"],
            "score": 1000,
            "distance_m": 300,
            "duration_ms": 8000,          # within wall-clock slack for instant test submit
            "credits_earned": 200,
            "enemies_killed": 30,
            "wave_reached": 5,
            "max_weapon_tier": 3,
        }
        stats.update(overrides)
        checksum = compute_run_checksum(start["session_token"], stats)
        payload = {
            "session_token": start["session_token"],
            "seed": start["seed"],
            "started_at": start["started_at"],
            "checksum": checksum,
        }
        payload.update(stats)
        return payload

    def _submit(self, payload):
        return self.client.post(
            reverse("arcade:marauder_submit"),
            data=json.dumps(payload),
            content_type="application/json",
        )


class MarauderRoutingTests(MarauderTestBase):
    def test_anonymous_redirects(self):
        c = Client()
        res = c.get(reverse("arcade:marauder_play"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/users/login/", res.url)

    def test_marauder_not_shadowed_by_catchall(self):
        # /arcade/marauder/ must resolve to the shooter, not the generic play view.
        match = resolve("/arcade/marauder/")
        self.assertEqual(match.view_name, "arcade:marauder_play")

    def test_play_creates_single_profile(self):
        r1 = self.client.get(reverse("arcade:marauder_play"))
        self.assertEqual(r1.status_code, 200)
        self.client.get(reverse("arcade:marauder_play"))
        self.assertEqual(PilotProfile.objects.filter(user=self.user).count(), 1)

    def test_lobby_and_leaderboard_render(self):
        # Lobby must still render with the extra Marauder card, and the
        # standalone leaderboard page must render.
        self.assertEqual(self.client.get(reverse("arcade:lobby")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("arcade:marauder_leaderboard")).status_code, 200
        )

    def test_leaderboard_json(self):
        res = self.client.get(reverse("arcade:marauder_leaderboard") + "?format=json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("global_top", data)
        self.assertIn("personal_top", data)


class MarauderTokenTests(MarauderTestBase):
    def test_start_issues_verifiable_token(self):
        start = self._start()
        self.assertIn("seed", start)
        self.assertIn("session_token", start)
        verified = verify_run_token(start["session_token"], self.user.id)
        self.assertIsNotNone(verified)
        self.assertEqual(verified[0], start["seed"])

    def test_token_bound_to_user(self):
        start = self._start()
        other = User.objects.create_user(username="pilot2", password="x")
        self.assertIsNone(verify_run_token(start["session_token"], other.id))


class MarauderSubmitTests(MarauderTestBase):
    def test_valid_submission_persists_and_ranks(self):
        start = self._start()
        res = self._submit(self._payload(start))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["run_status"], MarauderRun.STATUS_VALID)
        self.assertEqual(data["global_rank"], 1)
        self.assertEqual(data["personal_rank"], 1)

        run = MarauderRun.objects.get(pk=data["run_id"])
        self.assertEqual(run.status, MarauderRun.STATUS_VALID)

        profile = PilotProfile.objects.get(user=self.user)
        self.assertEqual(profile.total_runs, 1)
        self.assertEqual(profile.credits, 200)
        self.assertEqual(profile.best_score, 1000)

    def test_tampered_checksum_rejected(self):
        start = self._start()
        payload = self._payload(start)
        payload["score"] = 999999  # changed after checksum computed
        res = self._submit(payload)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json().get("reason"), "checksum")
        self.assertEqual(MarauderRun.objects.count(), 0)

    def test_seed_mismatch_rejected(self):
        start = self._start()
        payload = self._payload(start)
        payload["seed"] = "deadbeef" * 4
        res = self._submit(payload)
        self.assertEqual(res.status_code, 403)

    def test_invalid_token_rejected(self):
        start = self._start()
        payload = self._payload(start)
        payload["session_token"] = "not-a-valid-token"
        res = self._submit(payload)
        self.assertEqual(res.status_code, 403)

    def test_absurd_score_flagged_and_excluded(self):
        start = self._start()
        # Within distance/kill bounds but score far above the analytic ceiling.
        res = self._submit(self._payload(start, score=120000))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["run_status"], MarauderRun.STATUS_FLAGGED)

        # Flagged runs never appear on the board and don't move the PB.
        self.assertEqual(get_global_top(5), [])
        profile = PilotProfile.objects.get(user=self.user)
        self.assertEqual(profile.best_score, 0)
        self.assertEqual(profile.total_runs, 1)

    def test_duration_exceeds_wallclock_rejected(self):
        start = self._start()
        # 5 minutes of "duration" submitted instantly => impossible.
        res = self._submit(self._payload(start, duration_ms=300000))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["run_status"], MarauderRun.STATUS_REJECTED)
        self.assertEqual(get_global_top(5), [])


class MarauderLeaderboardTests(MarauderTestBase):
    def _make_run(self, user, score, status=MarauderRun.STATUS_VALID):
        from django.utils import timezone
        from arcade.services_marauder import _new_seed
        return MarauderRun.objects.create(
            user=user, seed=_new_seed(), score=score, distance_m=score, duration_ms=1000,
            status=status, started_at=timezone.now(),
        )

    def test_global_ordering_desc(self):
        self._make_run(self.user, 100)
        self._make_run(self.user, 500)
        self._make_run(self.user, 300)
        top = get_global_top(5)
        self.assertEqual([r["score"] for r in top], [500, 300, 100])
        self.assertEqual(top[0]["rank"], 1)

    def test_personal_excludes_other_users(self):
        other = User.objects.create_user(username="pilot2", password="x")
        self._make_run(other, 9999)
        self._make_run(self.user, 200)
        mine = get_user_top(self.user, 5)
        self.assertEqual([r["score"] for r in mine], [200])

    def test_flagged_excluded_from_boards(self):
        self._make_run(self.user, 800, status=MarauderRun.STATUS_FLAGGED)
        self._make_run(self.user, 400, status=MarauderRun.STATUS_VALID)
        self.assertEqual([r["score"] for r in get_global_top(5)], [400])


# Phase 2: replay protection and rate limiting. Does not re-test Phase 1
# (token signing, checksum computation, plausibility grading).


class MarauderReplayGuardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pilot_replay", password="x")
        self.client.force_login(self.user)
        cache.clear()  # rate-limit counters must not leak between tests

    def _valid_submit_payload(self, seed="a" * 32):
        """
        Builds a payload that should grade STATUS_VALID under Phase 1's
        plausibility bounds: well inside every ceiling in services_marauder.py.
        started_at is generated fresh each call so the wall-clock check
        (duration_ms <= wall_ms + WALL_CLOCK_SLACK_MS) always passes regardless
        of when the test suite actually runs.
        """
        started_at_iso = timezone.now().isoformat()
        token = make_run_token(self.user.id, seed, started_at_iso)
        stats = {
            "seed": seed,
            "score": 100,
            "distance_m": 20,
            "duration_ms": 5000,
            "enemies_killed": 1,
            "wave_reached": 1,
        }
        checksum = compute_run_checksum(token, stats)
        return {
            "session_token": token,
            "seed": seed,
            "checksum": checksum,
            "score": stats["score"],
            "distance_m": stats["distance_m"],
            "duration_ms": stats["duration_ms"],
            "credits_earned": 10,
            "enemies_killed": stats["enemies_killed"],
            "wave_reached": stats["wave_reached"],
            "max_weapon_tier": 1,
        }

    def test_duplicate_seed_rejected_with_409(self):
        url = reverse("arcade:marauder_submit")
        payload = self._valid_submit_payload()

        first = self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(MarauderRun.objects.filter(seed=payload["seed"]).count(), 1)

        second = self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            MarauderRun.objects.filter(seed=payload["seed"]).count(),
            1,
            "a duplicate submit must not create a second row",
        )

    def test_seed_unique_constraint_survives_a_direct_race(self):
        """
        Bypasses seed_already_submitted() entirely -- this proves the DATABASE
        constraint, not just the view-level pre-check, is what actually stops
        a genuine two-tabs-at-once race (the pre-check can't close that window
        by itself; see the comment in run_submit).
        """
        now = timezone.now()
        MarauderRun.objects.create(
            user=self.user, seed="racecondition0000000000000000", score=1, started_at=now,
        )
        with self.assertRaises(Exception):
            MarauderRun.objects.create(
                user=self.user, seed="racecondition0000000000000000", score=2, started_at=now,
            )


class MarauderRateLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pilot_rate", password="x")
        self.client.force_login(self.user)
        cache.clear()

    def test_run_start_rate_limited_after_threshold(self):
        from arcade.views_marauder import RUN_START_RATE_LIMIT

        url = reverse("arcade:marauder_start")
        for _ in range(RUN_START_RATE_LIMIT):
            response = self.client.post(url)
            self.assertEqual(response.status_code, 200)

        blocked = self.client.post(url)
        self.assertEqual(blocked.status_code, 429)

    def test_rate_limit_is_isolated_per_user(self):
        from arcade.views_marauder import RUN_START_RATE_LIMIT

        url = reverse("arcade:marauder_start")
        for _ in range(RUN_START_RATE_LIMIT):
            self.client.post(url)
        self.assertEqual(self.client.post(url).status_code, 429)

        other_user = User.objects.create_user(username="pilot_rate_2", password="x")
        self.client.force_login(other_user)
        self.assertEqual(
            self.client.post(url).status_code,
            200,
            "a different user must not inherit another user's rate limit",
        )


# Phase 4: core service-layer coverage that Phase 2 explicitly skipped.
# Token-bound-to-user and the VALID/FLAGGED/REJECTED submit paths already
# exist above; this class fills the remaining gaps without duplicating those.


class MarauderCoreLogicTests(TestCase):
    def test_puzzle_signer_token_is_rejected_as_marauder_run_token(self):
        """
        arcade.services (daily puzzles) and arcade.services_marauder must not
        share a signing-salt namespace. A structurally valid user:seed:iso
        payload signed by the puzzle signer must not unsign as a Marauder token.
        """
        from arcade.services import signer as puzzle_signer

        user_id = 42
        seed = "a" * 32
        started_at = timezone.now().isoformat()
        puzzle_token = puzzle_signer.sign(f"{user_id}:{seed}:{started_at}")
        self.assertIsNone(verify_run_token(puzzle_token, user_id))

    def test_checksum_changes_when_any_checksum_field_changes(self):
        from arcade.services_marauder import CHECKSUM_FIELDS

        token = "session-token-not-a-real-signer-output"
        stats = {
            "seed": "b" * 32,
            "score": 1000,
            "distance_m": 300,
            "duration_ms": 8000,
            "enemies_killed": 30,
            "wave_reached": 5,
        }
        self.assertEqual(len(CHECKSUM_FIELDS), 6)
        baseline = compute_run_checksum(token, stats)
        for field in CHECKSUM_FIELDS:
            mutated = dict(stats)
            original = mutated[field]
            mutated[field] = original + 1 if isinstance(original, int) else original + "x"
            self.assertNotEqual(
                compute_run_checksum(token, mutated),
                baseline,
                f"checksum ignored field {field}",
            )
