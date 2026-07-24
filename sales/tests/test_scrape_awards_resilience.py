"""Tests for scrape_awards per-date isolation and circuit breaker."""

from datetime import date, timedelta
from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase
from django.utils import timezone

from sales.management.commands.scrape_awards import (
    MAX_CONSECUTIVE_FAILURES,
    Command,
)
from sales.models import AwardImportBatch


class ScrapeAwardsResilienceTests(TestCase):
    def setUp(self):
        self.cmd = Command()
        self.cmd.stdout = type(
            "O", (), {"write": lambda *a, **k: None}
        )()
        self.cmd.stderr = type(
            "O", (), {"write": lambda *a, **k: None}
        )()

    def _batch(self, scrape_date, status=AwardImportBatch.SCRAPE_MISSING):
        return AwardImportBatch.objects.create(
            award_date=scrape_date,
            scrape_date=scrape_date,
            filename=f"scrape-{scrape_date.isoformat()}.txt",
            source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            scrape_status=status,
            last_attempted_at=timezone.now() - timedelta(hours=1),
        )

    def test_single_import_failure_marks_only_that_batch_failed(self):
        d1 = date(2026, 6, 7)
        d2 = date(2026, 6, 8)
        b1 = self._batch(d1)
        b2 = self._batch(d2)

        def fake_scrape(*, award_date, batch_id, on_page_complete, activity_log):
            on_page_complete([{"Award_Basic_Number": "X"}], 1, 1)
            return {
                "error": None,
                "expected_rows": 1,
                "pages_scraped": 1,
                "actual_rows": 1,
            }

        call_dates = []

        def fake_import(records, batch, aw_file_date):
            call_dates.append(aw_file_date)
            if aw_file_date == d1:
                raise DatabaseError("515 null url")
            return {
                "created_count": 1,
                "faux_created_count": 0,
                "mod_created_count": 0,
                "mod_skipped_count": 0,
                "warnings": [],
            }

        with (
            patch(
                "sales.management.commands.scrape_awards.scrape_awards_for_date",
                side_effect=fake_scrape,
            ),
            patch(
                "sales.management.commands.scrape_awards.import_aw_records",
                side_effect=fake_import,
            ),
            patch(
                "sales.management.commands.scrape_awards.queue_we_won_awards",
                return_value={"queued": 0, "skipped": 0, "errors": 0},
            ),
            patch(
                "intake.services.queue_we_won_drafts.queue_we_won_drafts",
                return_value={
                    "queued": 0,
                    "skipped": 0,
                    "errors": 0,
                    "sp_probe_errors": 0,
                },
            ),
            patch(
                "intake.services.award_ledger.upsert_ledger_for_batch",
                return_value={
                    "created": 0,
                    "updated": 0,
                    "we_won": 0,
                    "mods": 0,
                },
            ),
        ):
            ok1, reason1 = self.cmd._scrape_single_date_from_batch(b1)
            ok2, reason2 = self.cmd._scrape_single_date_from_batch(b2)

        b1.refresh_from_db()
        b2.refresh_from_db()
        self.assertFalse(ok1)
        self.assertIn("515", reason1 or "")
        self.assertEqual(b1.scrape_status, AwardImportBatch.SCRAPE_FAILED)
        self.assertTrue(ok2)
        self.assertIsNone(reason2)
        self.assertEqual(b2.scrape_status, AwardImportBatch.SCRAPE_SUCCESS)
        self.assertEqual(call_dates, [d1, d2])

    def test_batch_never_left_in_progress_after_import_exception(self):
        batch = self._batch(date(2026, 6, 9))
        def fake_scrape(*, award_date, batch_id, on_page_complete, activity_log):
            on_page_complete([{"Award_Basic_Number": "X"}], 1, 1)
            return {
                "error": None,
                "expected_rows": 1,
                "pages_scraped": 1,
                "actual_rows": 1,
            }

        with (
            patch(
                "sales.management.commands.scrape_awards.scrape_awards_for_date",
                side_effect=fake_scrape,
            ),
            patch(
                "sales.management.commands.scrape_awards.import_aw_records",
                side_effect=DatabaseError("boom"),
            ),
        ):
            ok, reason = self.cmd._scrape_single_date_from_batch(batch)

        batch.refresh_from_db()
        self.assertFalse(ok)
        self.assertIsNotNone(reason)
        self.assertNotEqual(
            batch.scrape_status, AwardImportBatch.SCRAPE_IN_PROGRESS
        )
        self.assertEqual(batch.scrape_status, AwardImportBatch.SCRAPE_FAILED)

    def test_circuit_breaker_aborts_remaining_queue(self):
        self.assertEqual(MAX_CONSECUTIVE_FAILURES, 3)
        dates = [date(2026, 6, d) for d in (10, 11, 12, 13)]
        batches = [self._batch(d) for d in dates]

        with (
            patch.object(
                self.cmd,
                "_fetch_available_dates",
                return_value=dates,
            ),
            patch.object(self.cmd, "_sync_dates_to_db"),
            patch.object(
                self.cmd,
                "_build_work_queue",
                return_value=batches,
            ),
            patch.object(
                self.cmd,
                "_scrape_single_date_from_batch",
                return_value=(False, "systemic fault"),
            ),
            patch.object(self.cmd, "_check_and_notify_expiring_dates"),
            patch.object(self.cmd, "_send_job_failure_email"),
            patch("sales.management.commands.scrape_awards.time.sleep"),
            self.assertRaises(SystemExit) as raised,
        ):
            self.cmd._run_full_reconciliation(dry_run=False)

        self.assertEqual(raised.exception.code, 1)
        # Fourth batch never scraped — still MISSING
        batches[3].refresh_from_db()
        self.assertEqual(
            batches[3].scrape_status, AwardImportBatch.SCRAPE_MISSING
        )
