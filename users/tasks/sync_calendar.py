"""
Two-way SharePoint calendar sync (Azure WebJob / run_background_tasks).

Pulls the SharePoint list into WorkCalendarEvent, then pushes any portal events
SharePoint is still missing. The push half is inert unless
SHAREPOINT_CALENDAR_PUSH_ENABLED and SHAREPOINT_CALENDAR_BACKFILL_ENABLED are on.
"""
import logging

from users.sharepoint_services import sync_sharepoint_calendar_two_way

logger = logging.getLogger("users.tasks.sync_calendar")


def run():
    try:
        stats = sync_sharepoint_calendar_two_way()
        logger.info("sync_calendar completed: %s", stats)
    except Exception:
        logger.exception("sync_calendar failed")
