"""Tests for award staging import failure cleanup and drift tripwire."""

from datetime import date
from unittest.mock import patch

from django.test import TestCase

from sales.models import AwardImportBatch, DibbsAward
from sales.services.awards_file_importer import import_aw_records


class ImportAwRecordsFailureCleanupTests(TestCase):
    def setUp(self):
        self.batch = AwardImportBatch.objects.create(
            award_date=date(2026, 7, 1),
            filename="test.html",
            source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            scrape_status=AwardImportBatch.SCRAPE_IN_PROGRESS,
        )

    def _record(self, abn="SPE7M1-26-C-0001"):
        return {
            "Award_Basic_Number": abn,
            "Delivery_Order_Number": "",
            "Delivery_Order_Counter": "",
            "Last_Mod_Posting_Date": "",
            "Awardee_CAGE_Code": "1ABC2",
            "Total_Contract_Price": "10.00",
            "Award_Date": "07-01-2026",
            "Posted_Date": "07-01-2026",
            "NSN_Part_Number": "1234567890123",
            "Nomenclature": "WIDGET",
            "Purchase_Request": "PR1",
            "Solicitation": "SPE7M126Q0001",
            "Pdf_Url": "",
            "award_basic_number_url": "https://example/basic.pdf",
            "award_basic_package_view_url": "",
            "delivery_order_number_url": "",
            "delivery_order_package_view_url": "",
        }

    def test_deletes_staging_and_reraises_when_proc_fails(self):
        with patch(
            "sales.services.awards_file_importer.connection"
        ) as mock_conn:
            stage_cursor = mock_conn.cursor.return_value.__enter__.return_value
            # executemany for staging succeeds; EXEC raises
            call_count = {"n": 0}

            def execute(sql, params=None):
                call_count["n"] += 1
                if "EXEC" in sql.upper():
                    raise RuntimeError("proc boom")
                # DELETE path — leave rowcount
                stage_cursor.rowcount = 3

            stage_cursor.execute.side_effect = execute

            # Also stage real ORM rows so we can assert cleanup path is invoked;
            # _stage_rows uses raw SQL via the mocked connection, so seed ORM rows
            # and assert _delete_staging_for_stage was attempted via DELETE SQL.
            with self.assertRaises(RuntimeError):
                import_aw_records(
                    [self._record()], self.batch, date(2026, 7, 1)
                )

            delete_calls = [
                c
                for c in stage_cursor.execute.call_args_list
                if c.args and "DELETE FROM dibbs_award_staging" in c.args[0]
            ]
            self.assertEqual(len(delete_calls), 1)

    def test_warns_on_possible_stored_proc_drift_when_urls_empty(self):
        DibbsAward.objects.create(
            notice_id="N1",
            source=DibbsAward.SOURCE_DIBBS_FILE,
            award_basic_number="SPE7M1-26-C-0001",
            delivery_order_number="",
            awardee_cage="1ABC2",
            nsn="1234567890123",
            purchase_request="PR1",
            sol_number="SPE7M126Q0001",
            award_date=date(2026, 7, 1),
            aw_file_date=date(2026, 7, 1),
            aw_import_batch=self.batch,
            award_basic_number_url="",
            is_faux=False,
        )

        with (
            patch("sales.services.awards_file_importer._stage_rows"),
            patch("sales.services.awards_file_importer._call_proc"),
            patch(
                "sales.services.contract_mods.max_dibbs_award_mod_id",
                return_value=0,
            ),
            patch(
                "sales.services.contract_mods.active_company_cage_codes",
                return_value=set(),
            ),
            patch("sales.services.contract_mods.match_new_mods_after_import"),
            self.assertLogs(
                "sales.services.awards_file_importer", level="WARNING"
            ) as logs,
        ):
            import_aw_records([self._record()], self.batch, date(2026, 7, 1))

        self.assertTrue(
            any("possible stored proc drift" in msg for msg in logs.output)
        )
