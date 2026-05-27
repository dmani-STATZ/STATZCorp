import logging

from django.db import connection

logger = logging.getLogger(__name__)


def run_readiness_check() -> tuple[bool, dict[str, str]]:
    """Lightweight DB readiness probe; no sensitive details in return value."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True, {"database": "ok"}
    except Exception:
        logger.exception("Health check: database unavailable")
        return False, {"database": "unavailable"}
