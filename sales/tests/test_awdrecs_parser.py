"""
Tests for sales.services.awdrecs_parser.parse_awdrecs_html.

Uses inline synthetic HTML constants for testing.
"""

from __future__ import annotations

import unittest

from sales.services.awdrecs_parser import REQUIRED_KEYS, parse_awdrecs_html

WITH_ROWS_HTML = """
<html><body>
<table id="ctl00_cph1_grdAwardSearch" cellspacing="0" cellpadding="4">
<tr>
  <th>#</th><th>Award/Basic Number</th><th>Delivery Order Number</th>
  <th>Delivery Order Counter</th><th>Last Mod Posting Date</th>
  <th>Awardee CAGE Code</th><th>Total Contact Price</th>
  <th>Award Date</th><th>Posted Date</th><th>NSN/Part Number</th>
  <th>Nomenclature</th><th>Purchase Request</th><th>Solicitation</th>
</tr>
<tr>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblRowNum">1</span></td>
  <td align="left" valign="top" style="width:200px;">
    <span id="ctl00_cph1_grdAwardSearch_ctl03_lblAwardBasicNumber"
          style="display:inline-block;width:200px;">
      <img src="space.gif" width="16" height="16" alt="-spacer-">TESTCONTRACT001 <br>
      <span style="font-size:9px;">
        &raquo; <a href="AwdRec.aspx?contract=TESTCONTRACT001&amp;dlv=&amp;cnt="
                   title="Award/Basic Package View" target="DIBBS">
          Award/Basic Package View
        </a>
      </span>
    </span>
  </td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblDeliveryOrder"></span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblDeliveryOrderCounter">&nbsp;</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblLastModPostingDate">06-02-2026</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblCage">3WGD1</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblTotalContactPrice">See Award Doc</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblAwardDate">06-02-2026</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblPostedDate">06-02-2026</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblNsn">1234567890123</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblNomenclature">TEST ITEM DESCRIPTION</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblPurchaseRequest">&nbsp;</span></td>
  <td><span id="ctl00_cph1_grdAwardSearch_ctl03_lblSolicitation">&nbsp;</span></td>
</tr>
</table>
</body></html>
"""

EMPTY_HTML = "<html><body><p>No records found.</p></body></html>"


# ---------------------------------------------------------------------------
# WITH_ROWS_HTML — CAGE 3WGD1, has awards today
# ---------------------------------------------------------------------------

class TestParseAwdrecsWithRows(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = parse_awdrecs_html(WITH_ROWS_HTML)

    # --- structural ---

    def test_at_least_one_row_parsed(self):
        self.assertGreater(len(self.rows), 0, "Expected >= 1 row from WITH_ROWS_HTML")

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
        """The parser must extract 'TESTCONTRACT001' from the row."""
        abns = [r["Award_Basic_Number"] for r in self.rows]
        self.assertIn(
            "TESTCONTRACT001",
            abns,
            f"Expected Award_Basic_Number 'TESTCONTRACT001' in parsed rows; got: {abns}",
        )

    def test_known_nsn_present(self):
        """The parser must extract '1234567890123' from the row."""
        nsns = [r["NSN_Part_Number"] for r in self.rows]
        self.assertIn(
            "1234567890123",
            nsns,
            f"Expected NSN_Part_Number '1234567890123' in parsed rows; got: {nsns}",
        )

    def test_every_cage_is_3WGD1(self):
        """Every row's Awardee_CAGE_Code must equal '3WGD1'."""
        for i, row in enumerate(self.rows):
            self.assertEqual(
                row["Awardee_CAGE_Code"],
                "3WGD1",
                f"Row {i} has unexpected CAGE code: {row['Awardee_CAGE_Code']!r}",
            )

    def test_award_date_non_empty(self):
        """Award_Date must be non-empty in every row (06-02-2026)."""
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
# EMPTY_HTML — no ctl00_cph1_grdAwardSearch table → []
# ---------------------------------------------------------------------------

class TestParseAwdrecsEmpty(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = parse_awdrecs_html(EMPTY_HTML)

    def test_returns_empty_list(self):
        """Zero-results fixture must produce []."""
        self.assertEqual(
            self.rows,
            [],
            f"Expected [] from EMPTY_HTML but got {len(self.rows)} row(s)",
        )


if __name__ == "__main__":
    unittest.main()
