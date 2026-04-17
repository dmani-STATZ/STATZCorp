"""
SharePoint calendar → WorkCalendarEvent sync (Azure WebJob / run_background_tasks).
"""
import logging

from users.sharepoint_services import sync_sharepoint_calendar

logger = logging.getLogger("users.tasks.sync_calendar")


def run():
    try:
        stats = sync_sharepoint_calendar()
        logger.info("sync_calendar completed: %s", stats)
    except Exception:
        logger.exception("sync_calendar failed")
