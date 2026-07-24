"""Tests for stored-proc version / column-list verification helpers."""

import io
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from sales.services.proc_verification import (
    columns_missing_from_any_insert,
    expected_proc_version,
    extract_insert_column_lists,
    extract_proc_version,
    read_repo_proc_sql,
)
from sales.services.proc_versions import PROC_VERSIONS

URL_COLUMNS = {
    "award_basic_number_url",
    "award_basic_package_view_url",
    "delivery_order_number_url",
    "delivery_order_package_view_url",
}


class ProcVersionAndInsertListTests(SimpleTestCase):
    def test_repo_proc_version_matches_proc_versions_module(self):
        sql = read_repo_proc_sql()
        version = extract_proc_version(sql)
        self.assertEqual(version, expected_proc_version())
        self.assertEqual(
            version, PROC_VERSIONS["dbo.usp_process_award_staging"]
        )

    def test_proc_version_marker_is_inside_procedure_body(self):
        sql = read_repo_proc_sql()
        create_idx = sql.upper().find("CREATE OR ALTER PROCEDURE")
        as_idx = sql.upper().find("\nAS\n", create_idx)
        begin_idx = sql.upper().find("BEGIN", as_idx)
        version_idx = sql.find("PROC_VERSION:")
        self.assertGreater(create_idx, -1)
        self.assertGreater(as_idx, create_idx)
        self.assertGreater(begin_idx, as_idx)
        self.assertGreater(version_idx, begin_idx)

    def test_all_insert_lists_include_four_url_columns(self):
        sql = read_repo_proc_sql()
        lists = extract_insert_column_lists(sql)
        self.assertGreaterEqual(len(lists), 2)
        for cols in lists:
            missing = URL_COLUMNS - cols
            self.assertEqual(
                missing,
                set(),
                f"INSERT INTO dibbs_award missing URL columns: {missing}",
            )

    def test_columns_missing_from_any_insert_detects_stripped_column(self):
        fixture = """
        INSERT INTO dibbs_award (
            notice_id, award_basic_number, pdf_url
        )
        SELECT 1, 2, 3
        """
        missing = columns_missing_from_any_insert(
            fixture, {"award_basic_number_url", "pdf_url"}
        )
        self.assertEqual(missing, ["award_basic_number_url"])


class VerifyStoredProcsCommandTests(TestCase):
    def test_exits_nonzero_on_version_mismatch(self):
        fake_deployed = (
            "-- PROC_VERSION: 1999-01-01.0\nCREATE PROCEDURE x AS BEGIN SELECT 1 END",
            "2026-01-01",
        )
        with (
            patch(
                "sales.management.commands.verify_stored_procs.connection"
            ) as mock_conn,
            patch(
                "sales.management.commands.verify_stored_procs.read_repo_proc_sql",
                return_value="-- PROC_VERSION: 2026-07-24.1\n",
            ),
            patch(
                "sales.management.commands.verify_stored_procs.expected_proc_version",
                return_value="2026-07-24.1",
            ),
            self.assertRaises(SystemExit) as raised,
        ):
            mock_conn.vendor = "microsoft"
            cursor = MagicMock()
            cursor.fetchone.return_value = fake_deployed
            cursor.fetchall.return_value = []
            mock_conn.cursor.return_value.__enter__.return_value = cursor
            call_command(
                "verify_stored_procs",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        self.assertEqual(raised.exception.code, 1)

    def test_exits_nonzero_when_required_column_absent_from_insert(self):
        repo_sql = """
        -- PROC_VERSION: 2026-07-24.1
        INSERT INTO dibbs_award (notice_id, award_basic_number)
        SELECT 1, 2
        INSERT INTO dibbs_award (notice_id, award_basic_number)
        SELECT 1, 2
        """
        fake_deployed = (repo_sql, "2026-01-01")
        with (
            patch(
                "sales.management.commands.verify_stored_procs.connection"
            ) as mock_conn,
            patch(
                "sales.management.commands.verify_stored_procs.read_repo_proc_sql",
                return_value=repo_sql,
            ),
            patch(
                "sales.management.commands.verify_stored_procs.expected_proc_version",
                return_value="2026-07-24.1",
            ),
            self.assertRaises(SystemExit) as raised,
        ):
            mock_conn.vendor = "microsoft"
            cursor = MagicMock()
            # First execute: fetch deployed definition; second: required columns
            cursor.fetchone.return_value = fake_deployed
            cursor.fetchall.return_value = [("award_basic_number_url",)]
            mock_conn.cursor.return_value.__enter__.return_value = cursor
            call_command("verify_stored_procs", stdout=io.StringIO(), stderr=io.StringIO())
        self.assertEqual(raised.exception.code, 1)
