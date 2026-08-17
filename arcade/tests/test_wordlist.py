"""Phase C — word list packaging, static non-exposure, single-load."""
import re
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

from arcade.puzzles import wordlist


class WordlistPackagingTestCase(SimpleTestCase):
    def test_answers_and_guesses_charset(self):
        word_re = re.compile(r"^[a-z]{5}$")
        self.assertTrue(len(wordlist.ANSWERS) > 0)
        for w in wordlist.ANSWERS:
            self.assertRegex(w, word_re)
        for w in wordlist.GUESSES:
            self.assertRegex(w, word_re)

    def test_answers_subset_of_guesses(self):
        self.assertTrue(set(wordlist.ANSWERS) <= wordlist.GUESSES)

    def test_answers_sorted_unique(self):
        self.assertEqual(wordlist.ANSWERS, tuple(sorted(set(wordlist.ANSWERS))))

    def test_wordlist_files_not_static_discoverable(self):
        """answers/guesses must never be served via /static/."""
        candidates = [
            "arcade/answers.txt",
            "arcade/guesses.txt",
            "arcade/wordlists/answers.txt",
            "arcade/wordlists/guesses.txt",
            "answers.txt",
            "guesses.txt",
            "wordlists/answers.txt",
            "wordlists/guesses.txt",
        ]
        for name in candidates:
            self.assertIsNone(
                finders.find(name),
                msg=f"Word list unexpectedly discoverable as static file: {name}",
            )

    def test_load_happens_exactly_once(self):
        self.assertEqual(wordlist._LOAD_COUNT, 1)
        # Accessing constants repeatedly must not re-read files / re-load.
        _ = wordlist.ANSWERS[0]
        _ = "crane" in wordlist.GUESSES
        _ = len(wordlist.ANSWERS)
        self.assertEqual(wordlist._LOAD_COUNT, 1)
