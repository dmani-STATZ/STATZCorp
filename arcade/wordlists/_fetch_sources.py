"""One-shot helper: download public Wordle word sources into CSV inputs.

Not used at runtime. Safe to re-run; overwrites source CSVs only.
"""
from __future__ import annotations

import csv
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources"
SOURCES.mkdir(parents=True, exist_ok=True)

WORD_RE = re.compile(r"^[a-z]{5}$")


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def normalize_lines(text: str) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        token = re.split(r"[,;\s]+", line)[0].strip().strip('"').lower()
        if WORD_RE.match(token) and token not in seen:
            seen.add(token)
            words.append(token)
    return words


def write_csv(path: Path, words: list[str], source_note: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "source_note"])
        for w in words:
            writer.writerow([w, source_note])


def main() -> None:
    answers = normalize_lines(
        fetch(
            "https://raw.githubusercontent.com/Kinkelin/WordleCompetition/"
            "main/data/official/shuffled_real_wordles.txt"
        )
    )
    write_csv(SOURCES / "01_official_answers.csv", answers, "kinkelin/official_answers")

    guesses = normalize_lines(
        fetch(
            "https://raw.githubusercontent.com/Kinkelin/WordleCompetition/"
            "main/data/official/combined_wordlist.txt"
        )
    )
    write_csv(SOURCES / "02_official_guesses.csv", guesses, "kinkelin/official_combined")

    extra = normalize_lines(
        fetch("https://raw.githubusercontent.com/tabatkins/wordle-list/main/words")
    )
    write_csv(SOURCES / "03_community_extra.csv", extra, "tabatkins/wordle-list")

    print(f"01 answers: {len(answers)}")
    print(f"02 guesses: {len(guesses)}")
    print(f"03 extra:   {len(extra)}")
    print(f"answers subset of official guesses: {set(answers) <= set(guesses)}")


if __name__ == "__main__":
    main()
