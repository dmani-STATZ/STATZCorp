"""
Load Wordle answer/guess lists once at import.

Files live under arcade/wordlists/ (NOT under static/). Runtime never
re-reads them per request — ANSWERS and GUESSES are module-level constants.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

WORDLIST_DIR = Path(__file__).resolve().parent.parent / "wordlists"
_WORD_RE = re.compile(r"^[a-z]{5}$")

# Incremented exactly once when this module finishes loading word files.
_LOAD_COUNT = 0


def _read_words(path: Path) -> list[str]:
    if not path.is_file():
        raise ImproperlyConfigured(f"Arcade word list missing: {path}")
    words: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        word = line.lower()
        if not _WORD_RE.match(word):
            raise ImproperlyConfigured(
                f"Invalid word in {path.name} line {lineno}: {raw!r} "
                f"(expected exactly 5 lowercase a-z letters)"
            )
        words.append(word)
    return words


def _load_wordlists() -> tuple[tuple[str, ...], frozenset[str]]:
    global _LOAD_COUNT
    _LOAD_COUNT += 1

    answers_list = _read_words(WORDLIST_DIR / "answers.txt")
    guesses_list = _read_words(WORDLIST_DIR / "guesses.txt")
    extra_list = _read_words(WORDLIST_DIR / "allow_extra.txt")

    if not answers_list:
        raise ImproperlyConfigured("Arcade answers.txt is empty")

    answers = tuple(sorted(set(answers_list)))
    guesses = frozenset(guesses_list) | frozenset(answers) | frozenset(extra_list)

    if not set(answers) <= guesses:
        missing = sorted(set(answers) - guesses)[:10]
        raise ImproperlyConfigured(
            f"Arcade answers not subset of guesses (sample missing: {missing})"
        )

    return answers, guesses


ANSWERS: tuple[str, ...]
GUESSES: frozenset[str]

ANSWERS, GUESSES = _load_wordlists()
