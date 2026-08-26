"""Tests for sales.services.dibbs_awards_scraper DIBBS max record limit safeguards."""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from sales.services.dibbs_awards_scraper import (
    DIBBS_MAX_DISPLAY_RECORDS,
    DIBBS_MAX_PAGES,
    GRID_CONTROL,
    NAV_TIMEOUT,
    _dopostback,
    click_next_ellipsis,
    get_expected_record_count,
    scrape_awards_for_date,
)


class TestDibbsAwardsScraperSafeguards(unittest.TestCase):
    def test_constants_defined(self):
        self.assertEqual(DIBBS_MAX_DISPLAY_RECORDS, 10000)
        self.assertEqual(DIBBS_MAX_PAGES, 200)

    def test_get_expected_record_count_parsing(self):
        html_sample = '<span id="ctl00_cph1_lblRecCount">10,163</span>'
        count = get_expected_record_count(html_sample)
        self.assertEqual(count, 10163)

        html_sample_small = '<span id="ctl00_cph1_lblRecCount">2,500</span>'
        self.assertEqual(get_expected_record_count(html_sample_small), 2500)

        self.assertEqual(get_expected_record_count("<div>No count</div>"), 0)

    @patch("sales.services.dibbs_awards_scraper.accept_dod_warning")
    @patch("sales.services.dibbs_awards_scraper.get_expected_record_count")
    @patch("sales.services.dibbs_awards_scraper._page_records_normalized")
    def test_scrape_awards_for_date_truncates_over_10k(
        self, mock_page_records, mock_get_count, mock_accept_dod
    ):
        mock_get_count.return_value = 10163
        mock_page_records.return_value = []

        fake_page = MagicMock()
        fake_page.content = MagicMock(return_value="<html></html>")
        fake_context = MagicMock()
        fake_context.new_page = MagicMock(return_value=fake_page)
        fake_browser = MagicMock()
        fake_browser.new_context = MagicMock(return_value=fake_context)

        fake_pw = MagicMock()
        fake_pw.chromium.launch = MagicMock(return_value=fake_browser)
        fake_pw_context = MagicMock()
        fake_pw_context.__enter__.return_value = fake_pw
        fake_pw_context.__exit__.return_value = None

        logs = []

        with (
            patch("playwright.sync_api.sync_playwright", return_value=fake_pw_context),
            patch("sales.services.dibbs_awards_scraper.time.sleep"),
            patch("sales.services.dibbs_awards_scraper._dopostback"),
        ):
            res = scrape_awards_for_date(
                award_date=date(2026, 7, 21),
                batch_id=1,
                on_page_complete=lambda recs, p, total: None,
                activity_log=logs.append,
            )

        self.assertTrue(res["is_truncated"])
        self.assertEqual(res["raw_expected_rows"], 10163)
        self.assertEqual(res["expected_rows"], 10000)
        self.assertTrue(any("caps display at 10,000" in log for log in logs))


class _ArmedNavigationPage:
    """Minimal page double that records whether expect_navigation is entered before the action."""

    def __init__(self):
        self.in_expect_navigation = False
        self.evaluate_armed = False
        self.click_armed = False
        self.wait_until = None
        self.timeout = None

    def expect_navigation(self, wait_until=None, timeout=None):
        self.wait_until = wait_until
        self.timeout = timeout
        return self

    def __enter__(self):
        self.in_expect_navigation = True
        return self

    def __exit__(self, *args):
        self.in_expect_navigation = False
        return False

    def evaluate(self, js):
        self.evaluate_armed = self.in_expect_navigation
        self.js = js

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def wait_for_selector(self, *args, **kwargs):
        return None

    def locator(self, selector):
        loc = MagicMock()
        link = MagicMock()
        link.inner_text.return_value = "..."
        link.get_attribute.return_value = "__doPostBack('ctl00$cph1$grdAwardSearch','Page$11')"

        def _click(*args, **kwargs):
            self.click_armed = self.in_expect_navigation

        link.click.side_effect = _click
        loc.all.return_value = [link]
        return loc


class TestPostbackNavigationArmed(unittest.TestCase):
    def test_dopostback_arms_expect_navigation_before_evaluate(self):
        page = _ArmedNavigationPage()
        _dopostback(page, "2")
        self.assertTrue(page.evaluate_armed)
        self.assertEqual(page.wait_until, "domcontentloaded")
        self.assertEqual(page.timeout, NAV_TIMEOUT)
        self.assertIn(GRID_CONTROL, page.js)
        self.assertIn("Page$2", page.js)

    def test_click_next_ellipsis_arms_expect_navigation_before_click(self):
        page = _ArmedNavigationPage()
        self.assertTrue(click_next_ellipsis(page))
        self.assertTrue(page.click_armed)
        self.assertEqual(page.wait_until, "domcontentloaded")
        self.assertEqual(page.timeout, NAV_TIMEOUT)

