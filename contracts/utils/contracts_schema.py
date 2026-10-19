from __future__ import annotations

from typing import Iterable, Optional

from django.db import connection
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType


def _is_report_ai_schema_table(name: str) -> bool:
    n = (name or "").lower()
    if n in ("auth_user", "django_content_type"):
        return True
    if n.startswith("contracts_") or n.startswith("suppliers_") or n.startswith("products_"):
        return True
    return False


def generate_db_schema_snapshot(*, extra_tables: Optional[Iterable[str]] = None) -> str:
    """
    Introspected schema snapshot for reports admin AI: contracts, suppliers, products
    app tables (by prefix) plus auth_user and django_content_type, merged with
    any extra table names passed in.
    """
    from reports.utils import generate_db_schema_snapshot as _introspect_snapshot

    with connection.cursor() as cursor:
        try:
            table_infos = connection.introspection.get_table_list(cursor)
        except Exception:
            return "(schema unavailable)"
    names: set[str] = set()
    for ti in table_infos:
        t = getattr(ti, "name", str(ti))
        if _is_report_ai_schema_table(t):
            names.add(t)
    for raw in extra_tables or []:
        x = (raw or "").strip()
        if x:
            names.add(x)
    if not names:
        return "(no tables matched schema filter)"
    return _introspect_snapshot(None, only_tables=sorted(names))
