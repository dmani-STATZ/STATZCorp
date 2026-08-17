"""
Wordle daily puzzle — server-authoritative grading.

Duplicate-letter grading is TWO-PASS and must not be "simplified":
  Pass 1: mark exact positional matches and CONSUME those answer letters.
  Pass 2: for each unmarked guess letter, mark 'present' only if an
          UNCONSUMED copy remains in the answer, then consume it.
"""
from __future__ import annotations

import random
import re
from collections import Counter
from datetime import date

from django.conf import settings

from .base import MoveRejected, PuzzleGame, derive_seed
from .wordlist import ANSWERS, GUESSES

_GUESS_RE = re.compile(r"^[a-z]{5}$")


def _build_answer_order() -> tuple[str, ...]:
    """Stable shuffled permutation of ANSWERS, derived from the fixed epoch date."""
    epoch = settings.ARCADE_WORDLE_EPOCH
    order = list(ANSWERS)
    seed_hex = derive_seed("wordle_order", epoch)
    random.Random(int(seed_hex[:16], 16)).shuffle(order)
    return tuple(order)


# Computed once at import — never reshuffled per request.
_ANSWER_ORDER: tuple[str, ...] = _build_answer_order()


def answer_for(puzzle_date: date) -> str:
    epoch = settings.ARCADE_WORDLE_EPOCH
    idx = (puzzle_date - epoch).days % len(_ANSWER_ORDER)
    return _ANSWER_ORDER[idx]


def grade(guess: str, answer: str) -> list[str]:
    """Returns 5 marks: 'correct' | 'present' | 'absent'.

    Pass 1: mark exact positional matches and CONSUME those answer letters.
    Pass 2: for each unmarked guess letter, mark 'present' only if an
            UNCONSUMED copy remains in the answer, then consume it.
            Otherwise 'absent'.

    A single-pass implementation is WRONG and will over-report 'present'
    on duplicate letters.
    """
    marks = [""] * 5
    remaining = Counter(answer)

    # Pass 1 — greens consume first.
    for i, (g, a) in enumerate(zip(guess, answer)):
        if g == a:
            marks[i] = "correct"
            remaining[g] -= 1

    # Pass 2 — yellows only while an unconsumed copy remains.
    for i, g in enumerate(guess):
        if marks[i]:
            continue
        if remaining[g] > 0:
            marks[i] = "present"
            remaining[g] -= 1
        else:
            marks[i] = "absent"

    return marks


class WordleGame(PuzzleGame):
    game_key = "wordle"
    display_name = "Wordle"
    enabled = True
    blurb = "Guess the hidden 5-letter word in six tries."
    score_label = "guesses"
    stale_score = 7

    def format_score(self, value, attempt=None) -> str:
        if value is None:
            return "—"
        if value == 7:
            return "did not solve"
        return f"{value} guesses"

    def generate(self, puzzle_date: date) -> dict:
        seed_hex = derive_seed(self.game_key, puzzle_date)
        return {
            "game_key": self.game_key,
            "puzzle_date": puzzle_date.isoformat(),
            "seed": seed_hex,
            "par": None,
            "answer": answer_for(puzzle_date),
        }

    def initial_state(self, puzzle: dict) -> dict:
        return {
            "guesses": [],
            "marks": [],
            "moves_used": 0,
            "last_move_at": None,
        }

    def apply_move(self, puzzle: dict, state: dict, move: dict) -> dict:
        guesses = list(state.get("guesses") or [])
        marks_rows = list(state.get("marks") or [])

        if len(guesses) >= 6:
            raise MoveRejected(
                "already_finished",
                "No guesses remaining.",
                http_status=409,
            )

        raw = ""
        if isinstance(move, dict):
            raw = move.get("guess", "")
        guess = str(raw).strip().lower()

        if not _GUESS_RE.match(guess):
            raise MoveRejected("malformed", "Guess must be exactly 5 letters.", word=guess)

        if guess not in GUESSES:
            raise MoveRejected("not_in_list", "Not in word list.", word=guess)

        marks = grade(guess, puzzle["answer"])
        guesses.append(guess)
        marks_rows.append(marks)

        return {
            "guesses": guesses,
            "marks": marks_rows,
            "moves_used": len(guesses),
            "last_move_at": state.get("last_move_at"),
        }

    def is_solved(self, puzzle: dict, state: dict) -> bool:
        marks_rows = state.get("marks") or []
        if not marks_rows:
            return False
        return all(m == "correct" for m in marks_rows[-1])

    def is_failed(self, puzzle: dict, state: dict) -> bool:
        guesses = state.get("guesses") or []
        return len(guesses) >= 6 and not self.is_solved(puzzle, state)

    def score_on_complete(self, puzzle: dict, state: dict) -> int:
        if self.is_solved(puzzle, state):
            return len(state.get("guesses") or [])
        return 7

    def client_payload(self, puzzle: dict, state: dict) -> dict:
        payload = {
            "game_key": self.game_key,
            "guesses": list(state.get("guesses") or []),
            "marks": list(state.get("marks") or []),
            "max_guesses": 6,
            "is_solved": self.is_solved(puzzle, state),
            "is_failed": self.is_failed(puzzle, state),
        }
        # Answer only after the attempt is terminal (view calls this post-persist).
        if payload["is_solved"] or payload["is_failed"]:
            payload["answer"] = puzzle["answer"]
        return payload
