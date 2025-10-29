from __future__ import annotations

import csv
import io
import re
from typing import List, Tuple, Iterable, Optional

from django.db import connection


FORBIDDEN_SQL = re.compile(r"\b(insert|update|delete|create|drop|alter|truncate|grant|revoke|copy|call|do|execute|comment)\b", re.I)


def is_safe_select(sql: str) -> Tuple[bool, str]:
    """Basic guardrails: allow SELECT/CTE only, single statement.

    Returns (ok, reason_if_not_ok)
    """
    q = (sql or "").strip()
    if not q:
        return False, "SQL is required"

    # Disallow multiple statements
    if ";" in q[:-1]:  # allow a trailing semicolon only
        return False, "Multiple SQL statements are not allowed"

    # Must start with SELECT or WITH
    if not (q.lower().startswith("select") or q.lower().startswith("with")):
        return False, "Only read-only SELECT queries are allowed"

    # Block dangerous keywords
    if FORBIDDEN_SQL.search(q):
        return False, "Dangerous SQL keywords detected"

    return True, ""


def apply_limit(sql: str, limit: int = 500) -> str:
    """Apply a preview limit in a dialect-aware way.

    - SQLite/Postgres/MySQL: append LIMIT N (if not present)
    - SQL Server: inject TOP N after SELECT (if not present)
    """
    q = (sql or "").strip()
    if not q:
        return q

    # Remove trailing semicolon so we can safely modify
    if q.endswith(";"):
        q = q[:-1]

    vendor = connection.vendor  # 'sqlite', 'postgresql', 'mysql', 'oracle' or engine-specific like 'microsoft'
    engine = connection.settings_dict.get("ENGINE", "")

    # SQL Server handling
    if vendor == "microsoft" or "mssql" in engine or "sql_server" in engine:
        if re.search(r"\btop\s+\d+\b", q, re.I):
            return q
        # Inject TOP N after the first SELECT
        return re.sub(r"(?i)^\s*select\s+", f"SELECT TOP {int(limit)} ", q, count=1)

    # Default: LIMIT syntax
    if re.search(r"\blimit\b", q, re.I):
        return q
    return f"{q} LIMIT {int(limit)}"


def run_select(sql: str, limit: int = 500) -> Tuple[List[str], List[Tuple]]:
    """Execute a safe, read-only SELECT and return (columns, rows)."""
    ok, reason = is_safe_select(sql)
    if not ok:
        raise ValueError(reason)
    q = apply_limit(sql, limit)

    # Normalize vendor-specific syntax if needed (e.g., LIMIT -> TOP for SQL Server)
    vendor = connection.vendor
    engine = connection.settings_dict.get("ENGINE", "")
    if vendor == "microsoft" or "mssql" in engine or "sql_server" in engine:
        # If LIMIT N at the end, move to TOP N after SELECT
        m = re.search(r"\blimit\s+(\d+)\s*$", q, re.I)
        if m and not re.search(r"\btop\s+\d+\b", q, re.I):
            n = m.group(1)
            q = re.sub(r"\s*\blimit\s+\d+\s*$", "", q, flags=re.I)
            q = re.sub(r"(?i)^\s*select\s+", f"SELECT TOP {n} ", q, count=1)

    with connection.cursor() as cur:
        cur.execute(q)
        cols = [c[0] for c in cur.description] if cur.description else []
        rows = cur.fetchall()
    return cols, rows


def rows_to_csv(columns: List[str], rows: List[Tuple]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    if columns:
        writer.writerow(columns)
    for r in rows:
        writer.writerow(["" if v is None else str(v) for v in r])
    return buf.getvalue().encode("utf-8")


# -------- Schema Introspection Helpers --------
def generate_db_schema_snapshot(prefixes: Optional[Iterable[str]] = None, *, only_tables: Optional[Iterable[str]] = None) -> str:
    """Return a text snapshot of DB schema suitable for LLM prompting.

    - Lists tables (filtered by optional `prefixes`)
    - For each table: columns with type/nullable, primary key, and foreign keys
    """
    try:
        introspection = connection.introspection
    except Exception:
        return "(schema unavailable)"

    with connection.cursor() as cursor:
        try:
            table_infos = introspection.get_table_list(cursor)
        except Exception:
            return "(schema unavailable)"

    table_names: List[str] = []
    only_lookup = {t.lower(): True for t in (only_tables or [])}
    for ti in table_infos:
        name = getattr(ti, "name", str(ti))
        if only_lookup:
            if name.lower() in only_lookup:
                table_names.append(name)
        elif prefixes:
            if any(name.startswith(p) for p in prefixes):
                table_names.append(name)
        else:
            table_names.append(name)
    table_names = sorted(set(table_names))

    lines: List[str] = []
    with connection.cursor() as cursor:
        for tname in table_names:
            lines.append(f"TABLE {tname}")
            # Columns
            try:
                desc = introspection.get_table_description(cursor, tname)
            except Exception:
                desc = []
            for col in desc:
                col_name = getattr(col, "name", str(col))
                try:
                    col_type = introspection.get_field_type(getattr(col, "type_code", None), col)
                except Exception:
                    col_type = ""
                null_ok = getattr(col, "null_ok", True)
                lines.append(f"- {col_name} {col_type}{' NULL' if null_ok else ' NOT NULL'}")
            # Constraints
            try:
                constraints = introspection.get_constraints(cursor, tname)
            except Exception:
                constraints = {}
            for cname, c in constraints.items():
                cols = ",".join(c.get("columns", []) or [])
                if c.get("primary_key"):
                    lines.append(f"- PK {cname}: {cols}")
                fk = c.get("foreign_key")
                if fk:
                    to_table, to_col = fk
                    lines.append(f"- FK {cname}: {cols} -> {to_table}({to_col})")
            lines.append("")
    return "\n".join(lines)
