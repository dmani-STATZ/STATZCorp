"""
Build arcade/wordlists/answers.txt and guesses.txt from source CSVs.

Runtime Wordle code never imports this module — it only reads the generated
.txt files (and allow_extra.txt). Re-run after editing sources/:

    python arcade/wordlists/build_wordlist.py

Rules
-----
- Every kept word must match ^[a-z]{5}$
- answers.txt  = sorted unique words from 01_official_answers.csv
- guesses.txt  = sorted unique union of all three source CSVs (+ answers)
- answers ⊆ guesses is enforced (script exits non-zero if violated)
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources"
WORD_RE = re.compile(r"^[a-z]{5}$")

ANSWER_CSV = SOURCES / "01_official_answers.csv"
GUESS_CSVS = (
    SOURCES / "01_official_answers.csv",
    SOURCES / "02_official_guesses.csv",
    SOURCES / "03_community_extra.csv",
)


def load_words(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing source CSV: {path}")
    words: set[str] = set()
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "word" not in reader.fieldnames:
            raise ValueError(f"{path} must have a 'word' column")
        for row in reader:
            raw = (row.get("word") or "").strip().lower()
            if not raw:
                continue
            if not WORD_RE.match(raw):
                print(f"WARN skip non-[a-z]{{5}} in {path.name}: {raw!r}", file=sys.stderr)
                continue
            words.add(raw)
    return words


def write_lines(path: Path, words: list[str]) -> None:
    path.write_text("\n".join(words) + ("\n" if words else ""), encoding="utf-8")


def main() -> int:
    answers = load_words(ANSWER_CSV)
    guesses: set[str] = set()
    for csv_path in GUESS_CSVS:
        guesses |= load_words(csv_path)

    if not answers:
        print("ERROR: answer list is empty", file=sys.stderr)
        return 1
    if not answers <= guesses:
        missing = sorted(answers - guesses)
        print(
            f"ERROR: {len(missing)} answer(s) missing from guess union "
            f"(first: {missing[:10]})",
            file=sys.stderr,
        )
        return 1

    answer_list = sorted(answers)
    guess_list = sorted(guesses)
    write_lines(ROOT / "answers.txt", answer_list)
    write_lines(ROOT / "guesses.txt", guess_list)

    print(f"Wrote {len(answer_list)} answers -> {ROOT / 'answers.txt'}")
    print(f"Wrote {len(guess_list)} guesses -> {ROOT / 'guesses.txt'}")
    print("answers subset of guesses: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
