import logging

from django.core.management.base import BaseCommand

from sales.tasks.send_queued_rfqs import send_queued_rfqs
from users.tasks.sync_calendar import run as sync_sharepoint_calendar_task

logger = logging.getLogger("core.background_tasks")


class Command(BaseCommand):
    help = "Runs all scheduled background tasks in sequence"

    def handle(self, *args, **options):
        tasks = [
            ("send_queued_rfqs", send_queued_rfqs),
            ("sync_sharepoint_calendar", sync_sharepoint_calendar_task),
        ]
        for name, fn in tasks:
            logger.info("Starting task: %s", name)
            try:
                fn()
                logger.info("Completed task: %s", name)
            except Exception:
                logger.exception("Task failed: %s", name)
