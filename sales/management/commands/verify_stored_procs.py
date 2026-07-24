"""Detect drift between repository SQL and manually deployed SQL Server procs."""

import logging
import sys

from django.core.management.base import BaseCommand
from django.db import connection

from sales.services.proc_verification import (
    PROC_NAME,
    SQL_PATH,
    columns_missing_from_any_insert,
    expected_proc_version,
    extract_proc_version,
    read_repo_proc_sql,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Verify manually deployed SQL Server stored procedures against repo "
        "PROC_VERSION and INSERT column coverage. Exits non-zero on drift."
    )

    def _fail(self, message: str) -> None:
        logger.critical(message)
        self.stderr.write(self.style.ERROR(f"CRITICAL: {message}"))
        self._failed = True

    def handle(self, *args, **options):
        self._failed = False

        if connection.vendor != "microsoft":
            self.stdout.write(
                f"Skipped stored-procedure verification for {connection.vendor}."
            )
            return

        try:
            repo_definition = read_repo_proc_sql()
        except OSError as exc:
            self._fail(f"Cannot read repository procedure {SQL_PATH}: {exc}")
            sys.exit(1)

        expected = expected_proc_version(PROC_NAME)
        repo_version = extract_proc_version(repo_definition)
        if repo_version != expected:
            self._fail(
                f"Repository {SQL_PATH} PROC_VERSION={repo_version!r} does not "
                f"match expected {expected!r} in proc_versions.py."
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT sm.definition, o.modify_date
                FROM sys.sql_modules sm
                INNER JOIN sys.objects o ON o.object_id = sm.object_id
                WHERE sm.object_id = OBJECT_ID(%s)
                """,
                [PROC_NAME],
            )
            deployed = cursor.fetchone()

        if not deployed:
            self._fail(
                f"{PROC_NAME} is missing. Deploy {SQL_PATH} manually via SSMS."
            )
            sys.exit(1)

        deployed_definition, modify_date = deployed
        deployed_version = extract_proc_version(deployed_definition)
        if deployed_version != expected:
            self._fail(
                f"{PROC_NAME} PROC_VERSION drift: deployed={deployed_version!r}, "
                f"expected={expected!r}. Redeploy {SQL_PATH} via SSMS "
                f"(database modify_date={modify_date})."
            )

        required = self._required_not_null_columns_without_default()
        missing = columns_missing_from_any_insert(repo_definition, required)
        if missing:
            self._fail(
                f"{PROC_NAME} INSERT INTO dibbs_award is missing required "
                f"NOT NULL column(s) with no default: {', '.join(missing)}. "
                f"Update {SQL_PATH} and bump PROC_VERSION."
            )

        if self._failed:
            sys.exit(1)

        self.stdout.write(
            self.style.SUCCESS(
                f"Verified {PROC_NAME}: PROC_VERSION={expected} "
                f"(database modify_date={modify_date})."
            )
        )

    def _required_not_null_columns_without_default(self) -> set[str]:
        """dibbs_award NOT NULL columns that have no default and are not identity."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.name
                FROM sys.columns c
                INNER JOIN sys.tables t ON t.object_id = c.object_id
                WHERE t.name = N'dibbs_award'
                  AND c.is_nullable = 0
                  AND c.is_identity = 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM sys.default_constraints dc
                      WHERE dc.parent_object_id = c.object_id
                        AND dc.parent_column_id = c.column_id
                  )
                """
            )
            return {row[0].lower() for row in cursor.fetchall()}
