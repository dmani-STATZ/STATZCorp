"""Helpers for verifying manually deployed stored procedures against the repo."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

from sales.services.proc_versions import PROC_VERSIONS

PROC_NAME = "dbo.usp_process_award_staging"
SQL_PATH = Path(settings.BASE_DIR) / "sales" / "sql" / "usp_process_award_staging.sql"

_PROC_VERSION_RE = re.compile(r"PROC_VERSION:\s*(\S+)", re.IGNORECASE)
_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+dibbs_award\s*\((.*?)\)",
    re.IGNORECASE | re.DOTALL,
)


def extract_proc_version(definition: str | None) -> str | None:
    if not definition:
        return None
    match = _PROC_VERSION_RE.search(definition)
    return match.group(1) if match else None


def expected_proc_version(proc_name: str = PROC_NAME) -> str:
    return PROC_VERSIONS[proc_name]


def extract_insert_column_lists(sql_text: str) -> list[set[str]]:
    """Return the column set for every INSERT INTO dibbs_award (...) in sql_text."""
    lists: list[set[str]] = []
    for match in _INSERT_RE.finditer(sql_text):
        raw = match.group(1)
        cols = {
            part.strip().lower()
            for part in raw.split(",")
            if part.strip()
        }
        lists.append(cols)
    return lists


def columns_missing_from_any_insert(
    sql_text: str, required_columns: set[str]
) -> list[str]:
    """Columns in required_columns absent from at least one INSERT column list."""
    required = {c.lower() for c in required_columns}
    missing: set[str] = set()
    for cols in extract_insert_column_lists(sql_text):
        missing |= required - cols
    return sorted(missing)


def read_repo_proc_sql() -> str:
    return SQL_PATH.read_text(encoding="utf-8")
