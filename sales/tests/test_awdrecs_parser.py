"""
Tests for sales.services.awdrecs_parser.parse_awdrecs_html.

Reads real DIBBS fixture files — no inline HTML stubs.

Fixtures required (placed by the human before running):
    sales/tests/fixtures/awdrecs_with_rows.html
        CAGE 3WGD1, Posted Today; must contain >= 1 award row including
        Award_Basic_Number == "SPE4A525P5041".
    sales/tests/fixtures/awdrecs_empty.html
        A CAGE with 0 awards today — no ctl00_cph1_grdAwardSearch table.

Run with:
    python manage.py test sales.tests.test_awdrecs_parser
"""

from __future__ import annotations

import pathlib
import unittest

from sales.services.awdrecs_parser import REQUIRED_KEYS, parse_awdrecs_html

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    path = FIXTURE_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Fixture file not found: {path}\n"
            "Place the fixture HTML files in sales/tests/fixtures/ before running tests."
        )
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# awdrecs_with_rows.html — CAGE 3WGD1, has awards today
# ---------------------------------------------------------------------------

class TestParseAwdrecsWithRows(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = parse_awdrecs_html(_load("awdrecs_with_rows.html"))

    # --- structural ---

    def test_at_least_one_row_parsed(self):
        self.assertGreater(len(self.rows), 0, "Expected >= 1 row from awdrecs_with_rows.html")

    def test_all_required_keys_in_every_row(self):
        for i, row in enumerate(self.rows):
            missing = REQUIRED_KEYS - set(row.keys())
            self.assertFalse(
                missing,
                f"Row {i} is missing required keys: {sorted(missing)}",
            )

    def test_no_none_values(self):
        """All values must be str, never None."""
        for i, row in enumerate(self.rows):
            for key in REQUIRED_KEYS:
                self.assertIsInstance(
                    row[key],
                    str,
                    f"Row {i} key {key!r} is not str: {row[key]!r}",
                )

    def test_no_nbsp_in_values(self):
        """Non-breaking spaces must be normalised away."""
        for i, row in enumerate(self.rows):
            for key, val in row.items():
                self.assertNotIn(
                    "\xa0",
                    val,
                    f"Row {i} key {key!r} still contains \\xa0 (nbsp): {val!r}",
                )

    # --- content ---

    def test_known_award_basic_number_present(self):
        """The fixture for CAGE 3WGD1 must include SPE4A525P5041."""
        abns = [r["Award_Basic_Number"] for r in self.rows]
        self.assertIn(
            "SPE4A525P5041",
            abns,
            f"Expected Award_Basic_Number 'SPE4A525P5041' in parsed rows; got: {abns}",
        )

    def test_every_cage_is_3WGD1(self):
        """Every row's Awardee_CAGE_Code must equal '3WGD1' (CAGE-filtered search)."""
        for i, row in enumerate(self.rows):
            self.assertEqual(
                row["Awardee_CAGE_Code"],
                "3WGD1",
                f"Row {i} has unexpected CAGE code: {row['Awardee_CAGE_Code']!r}",
            )

    def test_award_date_non_empty(self):
        """Award_Date must be non-empty in every row (fixture has 06-02-2026)."""
        for i, row in enumerate(self.rows):
            self.assertTrue(
                row["Award_Date"].strip(),
                f"Row {i} has an empty Award_Date",
            )

    def test_price_kept_verbatim(self):
        """Total_Contract_Price == 'See Award Doc' (do NOT coerce)."""
        for i, row in enumerate(self.rows):
            self.assertEqual(
                row["Total_Contract_Price"],
                "See Award Doc",
                f"Row {i} Total_Contract_Price not 'See Award Doc': {row['Total_Contract_Price']!r}",
            )


# ---------------------------------------------------------------------------
# awdrecs_empty.html — no ctl00_cph1_grdAwardSearch table → []
# ---------------------------------------------------------------------------

class TestParseAwdrecsEmpty(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = parse_awdrecs_html(_load("awdrecs_empty.html"))

    def test_returns_empty_list(self):
        """Zero-results fixture must produce []."""
        self.assertEqual(
            self.rows,
            [],
            f"Expected [] from awdrecs_empty.html but got {len(self.rows)} row(s)",
        )


if __name__ == "__main__":
    unittest.main()
