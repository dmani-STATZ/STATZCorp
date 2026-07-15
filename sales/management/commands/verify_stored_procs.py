"""Detect drift between repository SQL and manually deployed SQL Server procs."""

import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

logger = logging.getLogger(__name__)

PROC_NAME = "dbo.usp_process_award_staging"
REQUIRED_GUARD = "isnull(s.pdf_url"
SQL_PATH = Path(settings.BASE_DIR) / "sales" / "sql" / "usp_process_award_staging.sql"


class Command(BaseCommand):
    help = "Verify manually deployed SQL Server stored procedures against repo guards."

    def _warn(self, message):
        logger.warning(message)
        self.stdout.write(self.style.WARNING(f"WARNING: {message}"))

    def handle(self, *args, **options):
        if connection.vendor != "microsoft":
            self.stdout.write(
                f"Skipped stored-procedure verification for {connection.vendor}."
            )
            return

        try:
            repo_definition = SQL_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            self._warn(f"Cannot read repository procedure {SQL_PATH}: {exc}")
            return

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
            self._warn(
                f"{PROC_NAME} is missing. Deploy {SQL_PATH} manually via SSMS."
            )
            return

        deployed_definition, modify_date = deployed
        repo_has_guard = REQUIRED_GUARD in repo_definition.lower()
        deployed_has_guard = REQUIRED_GUARD in (deployed_definition or "").lower()

        if repo_has_guard != deployed_has_guard:
            self._warn(
                f"{PROC_NAME} has drifted from {SQL_PATH}: repository "
                f"pdf_url ISNULL guard={repo_has_guard}, deployed "
                f"guard={deployed_has_guard}. Redeploy manually via SSMS."
            )
            return

        if not repo_has_guard:
            self._warn(
                f"Neither {SQL_PATH} nor deployed {PROC_NAME} contains the "
                "required ISNULL(s.pdf_url, '') guard."
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Verified {PROC_NAME}: pdf_url ISNULL guard is deployed "
                f"(database modify_date={modify_date})."
            )
        )
