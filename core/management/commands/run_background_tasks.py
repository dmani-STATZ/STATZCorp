import logging

from django.core.management.base import BaseCommand

from sales.tasks.send_queued_rfqs import send_queued_rfqs

logger = logging.getLogger("core.background_tasks")


class Command(BaseCommand):
    help = "Runs all scheduled background tasks in sequence"

    def handle(self, *args, **options):
        tasks = [
            ("send_queued_rfqs", send_queued_rfqs),
        ]
        for name, fn in tasks:
            logger.info("Starting task: %s", name)
            try:
                fn()
                logger.info("Completed task: %s", name)
            except Exception:
                logger.exception("Task failed: %s", name)
