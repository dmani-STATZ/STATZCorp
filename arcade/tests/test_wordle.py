"""Phase D/G — Wordle grading, answer selection, gameplay, redaction."""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from arcade.models import ArcadeAttempt, WordleRejectedGuess
from arcade.puzzles.wordle import WordleGame, answer_for, grade, _ANSWER_ORDER
from arcade.puzzles.wordlist import ANSWERS, GUESSES
from arcade.services import compute_handicap, get_arcade_today

User = get_user_model()

# Hand-derived from the mandatory two-pass rule (greens consume first).
# NOTE: The original Phase D brief table disagreed with that rule on several
# duplicate-letter rows; these expectations follow the written algorithm.
GRADE_CASES = [
    ("robot", "oozes", ["present", "correct", "absent", "absent", "absent"]),
    ("erase", "speed", ["present", "absent", "present", "present", "absent"]),
    ("abbey", "babes", ["present", "present", "correct", "correct", "absent"]),
    ("sissy", "essay", ["absent", "present", "correct", "absent", "correct"]),
    ("array", "radar", ["present", "present", "absent", "correct", "present"]),
    ("crane", "crane", ["correct", "correct", "correct", "correct", "correct"]),
    ("ghost", "blimp", ["absent", "absent", "absent", "absent", "absent"]),
]


class WordleGradeTestCase(SimpleTestCase):
    def test_seven_duplicate_letter_cases(self):
        for answer, guess, expected in GRADE_CASES:
            with self.subTest(answer=answer, guess=guess):
                self.assertEqual(grade(guess, answer), expected)

    def test_present_plus_correct_never_exceeds_answer_count(self):
        rng = random.Random(42)
        sample_answers = list(ANSWERS[:200])
        sample_guesses = list(GUESSES)
        for _ in range(300):
            answer = rng.choice(sample_answers)
            guess = rng.choice(sample_guesses)
            marks = grade(guess, answer)
            answer_counts = Counter(answer)
            credited = Counter()
            for g, m in zip(guess, marks):
                if m in ("correct", "present"):
                    credited[g] += 1
            for letter, count in credited.items():
                self.assertLessEqual(
                    count,
                    answer_counts[letter],
                    msg=f"over-credited {letter!r} for answer={answer} guess={guess} marks={marks}",
                )


class WordleAnswerSelectionTestCase(SimpleTestCase):
    def test_same_date_same_word(self):
        d = date(2026, 3, 15)
        self.assertEqual(answer_for(d), answer_for(d))

    def test_full_pool_no_repeats_then_wraps(self):
        epoch = settings.ARCADE_WORDLE_EPOCH
        n = len(_ANSWER_ORDER)
        self.assertEqual(n, len(ANSWERS))
        seen = [answer_for(epoch + timedelta(days=i)) for i in range(n)]
        self.assertEqual(len(set(seen)), n)
        self.assertEqual(
            answer_for(epoch + timedelta(days=n)),
            answer_for(epoch),
        )

    def test_date_before_epoch_returns_valid_word(self):
        before = settings.ARCADE_WORDLE_EPOCH - timedelta(days=1)
        word = answer_for(before)
        self.assertRegex(word, r"^[a-z]{5}$")
        self.assertIn(word, ANSWERS)


class WordlePayloadRedactionTestCase(SimpleTestCase):
    def setUp(self):
        self.game = WordleGame()
        self.puzzle = self.game.generate(date(2026, 8, 14))
        # Pick a wrong guess so we can fill 5 rows without solving.
        answer = self.puzzle["answer"]
        self.wrong = next(w for w in ANSWERS if w != answer)

    def test_no_answer_while_in_progress(self):
        state = self.game.initial_state(self.puzzle)
        for i in range(5):
            state = self.game.apply_move(self.puzzle, state, {"guess": self.wrong})
            payload = self.game.client_payload(self.puzzle, state)
            self.assertNotIn("answer", payload, msg=f"answer leaked after guess {i + 1}")
            self.assertFalse(payload["is_solved"])
            self.assertFalse(payload["is_failed"])

    def test_answer_present_after_solve(self):
        state = self.game.initial_state(self.puzzle)
        state = self.game.apply_move(
            self.puzzle, state, {"guess": self.puzzle["answer"]}
        )
        payload = self.game.client_payload(self.puzzle, state)
        self.assertTrue(payload["is_solved"])
        self.assertEqual(payload["answer"], self.puzzle["answer"])

    def test_answer_present_after_loss(self):
        state = self.game.initial_state(self.puzzle)
        for _ in range(6):
            state = self.game.apply_move(self.puzzle, state, {"guess": self.wrong})
        payload = self.game.client_payload(self.puzzle, state)
        self.assertTrue(payload["is_failed"])
        self.assertEqual(payload["answer"], self.puzzle["answer"])


class WordleGameplayTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="wordle_player",
            password="Password123!",
            first_name="Word",
            last_name="Player",
        )
        self.client = Client()
        self.client.login(username="wordle_player", password="Password123!")
        self.game = WordleGame()

    def _start(self):
        res = self.client.post(reverse("arcade:start", kwargs={"game_key": "wordle"}))
        self.assertEqual(res.status_code, 200)
        return res.json()

    def _move(self, attempt_id, token, guess):
        return self.client.post(
            reverse("arcade:move", kwargs={"game_key": "wordle"}),
            data=json.dumps({
                "attempt_id": attempt_id,
                "token": token,
                "move": {"guess": guess},
            }),
            content_type="application/json",
        )

    def test_second_start_returns_same_attempt(self):
        d1 = self._start()
        d2 = self._start()
        self.assertEqual(d1["attempt_id"], d2["attempt_id"])
        self.assertEqual(
            ArcadeAttempt.objects.filter(user=self.user, game_key="wordle").count(),
            1,
        )

    def test_solve_on_third_guess(self):
        data = self._start()
        attempt = ArcadeAttempt.objects.get(pk=data["attempt_id"])
        puzzle = self.game.generate(attempt.puzzle_date)
        answer = puzzle["answer"]
        wrong = next(w for w in ANSWERS if w != answer)

        for _ in range(2):
            res = self._move(data["attempt_id"], data["token"], wrong)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["attempt_status"], "in_progress")

        res = self._move(data["attempt_id"], data["token"], answer)
        body = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body["attempt_status"], "solved")
        self.assertEqual(body["score"], 3)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ArcadeAttempt.STATUS_SOLVED)
        self.assertEqual(attempt.score, 3)

    def test_six_wrong_guesses_fail(self):
        data = self._start()
        attempt = ArcadeAttempt.objects.get(pk=data["attempt_id"])
        puzzle = self.game.generate(attempt.puzzle_date)
        wrong = next(w for w in ANSWERS if w != puzzle["answer"])

        for i in range(6):
            res = self._move(data["attempt_id"], data["token"], wrong)
            self.assertEqual(res.status_code, 200)
            body = res.json()
            if i < 5:
                self.assertEqual(body["attempt_status"], "in_progress")
            else:
                self.assertEqual(body["attempt_status"], "failed")
                self.assertEqual(body["score"], 7)
                self.assertIn("answer", body["payload"])

        res7 = self._move(data["attempt_id"], data["token"], wrong)
        self.assertEqual(res7.status_code, 409)

    def test_not_in_list_logs_rejection(self):
        data = self._start()
        fake = "xqzqy"
        self.assertNotIn(fake, GUESSES)
        state_before = ArcadeAttempt.objects.get(pk=data["attempt_id"]).get_state()

        res = self._move(data["attempt_id"], data["token"], fake)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["reason"], "not_in_list")

        attempt = ArcadeAttempt.objects.get(pk=data["attempt_id"])
        self.assertEqual(attempt.get_state(), state_before)
        rej = WordleRejectedGuess.objects.get(word=fake)
        self.assertEqual(rej.hit_count, 1)

        self._move(data["attempt_id"], data["token"], fake)
        rej.refresh_from_db()
        self.assertEqual(rej.hit_count, 2)

    def test_allow_extra_accepted_after_reload(self):
        extra_path = Path(settings.BASE_DIR) / "arcade" / "wordlists" / "allow_extra.txt"
        original = extra_path.read_text(encoding="utf-8")
        # Pick a 5-letter word not already in GUESSES (unlikely) or temporarily
        # inject via module patch after reload.
        candidate = "zzqqz"
        try:
            extra_path.write_text(original + f"\n{candidate}\n", encoding="utf-8")
            import importlib
            import arcade.puzzles.wordlist as wl_mod
            import arcade.puzzles.wordle as wordle_mod

            importlib.reload(wl_mod)
            # Rebind GUESSES used by apply_move
            with mock.patch.object(wordle_mod, "GUESSES", wl_mod.GUESSES):
                self.assertIn(candidate, wl_mod.GUESSES)
                data = self._start()
                # Force a fresh game apply via patched module path
                game = WordleGame()
                attempt = ArcadeAttempt.objects.get(pk=data["attempt_id"])
                puzzle = game.generate(attempt.puzzle_date)
                # Direct apply_move with patched GUESSES
                state = game.initial_state(puzzle)
                with mock.patch("arcade.puzzles.wordle.GUESSES", wl_mod.GUESSES):
                    new_state = game.apply_move(puzzle, state, {"guess": candidate})
                self.assertEqual(new_state["guesses"][-1], candidate)
        finally:
            extra_path.write_text(original, encoding="utf-8")
            import importlib
            import arcade.puzzles.wordlist as wl_mod
            importlib.reload(wl_mod)

    def test_idle_cap_between_guesses(self):
        data = self._start()
        attempt = ArcadeAttempt.objects.get(pk=data["attempt_id"])
        puzzle = self.game.generate(attempt.puzzle_date)
        wrong = next(w for w in ANSWERS if w != puzzle["answer"])

        ten_mins_ago = timezone.now() - timedelta(minutes=10)
        attempt.started_at = ten_mins_ago
        attempt.save()

        res = self._move(data["attempt_id"], data["token"], wrong)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["active_ms"], 120000)

    def test_handicap_mixed_solved_and_failed(self):
        today = get_arcade_today()
        # 3 solved @ scores 3,4,5 and 2 failed @ 7 → avg 5.2
        scores_and_status = [
            (3, ArcadeAttempt.STATUS_SOLVED),
            (4, ArcadeAttempt.STATUS_SOLVED),
            (5, ArcadeAttempt.STATUS_SOLVED),
            (7, ArcadeAttempt.STATUS_FAILED),
            (7, ArcadeAttempt.STATUS_FAILED),
        ]
        for i, (score, status) in enumerate(scores_and_status):
            ArcadeAttempt.objects.create(
                user=self.user,
                game_key="wordle",
                puzzle_date=today - timedelta(days=i + 1),
                seed="seed",
                par=None,
                moves_used=score if status == ArcadeAttempt.STATUS_SOLVED else 6,
                score=score,
                status=status,
                started_at=timezone.now(),
                completed_at=timezone.now(),
            )
        h = compute_handicap(self.user, "wordle")
        self.assertEqual(h["handicap"], 5.2)
        self.assertEqual(h["display"], "+5.2")
