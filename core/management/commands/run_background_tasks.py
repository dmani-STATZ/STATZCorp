import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from core.models import ScheduledTask
from sales.tasks.send_queued_rfqs import send_queued_rfqs
from sales.tasks.poll_we_won_today import poll_we_won_today_task
from users.tasks.sync_calendar import run as sync_sharepoint_calendar_task
from mailer.tasks.dispatch_campaigns import dispatch_campaigns
from mailer.tasks.generate_ai import process_ai_snippets
from mailer.tasks.dispatch_followups import dispatch_followups
from sales.tasks.check_dibbs_notices import run as check_dibbs_notices_task
from intake.tasks.reconcile_award_ledger import reconcile_award_ledger_task

logger = logging.getLogger("core.background_tasks")

TASK_FUNCTIONS = {
    "send_queued_rfqs": send_queued_rfqs,
    "poll_we_won_today": poll_we_won_today_task,
    "sync_sharepoint_calendar": sync_sharepoint_calendar_task,
    "dispatch_campaigns": dispatch_campaigns,
    "process_ai_snippets": process_ai_snippets,
    "dispatch_followups": dispatch_followups,
    "check_dibbs_notices": check_dibbs_notices_task,
    "reconcile_award_ledger": reconcile_award_ledger_task,
}


class Command(BaseCommand):
    help = "Runs scheduled background tasks whose intervals have elapsed"

    def handle(self, *args, **options):
        now = timezone.now()

        # Step A — Thaw pass (stale lock detection)
        stale_pks = []
        for task in ScheduledTask.objects.filter(is_running=True):
            if task.last_run_at is not None and now >= task.last_run_at + timedelta(minutes=task.interval_minutes * 3):
                stale_pks.append(task.pk)

        if stale_pks:
            ScheduledTask.objects.filter(pk__in=stale_pks).update(
                is_running=False,
                freeze_count=F('freeze_count') + 1,
            )
            for task in ScheduledTask.objects.filter(pk__in=stale_pks):
                logger.warning(
                    "Stale lock cleared on task: %s (freeze_count now incremented)",
                    task.name,
                )

        # Step B — Determine due tasks
        due_tasks = []
        for task in ScheduledTask.objects.filter(is_enabled=True, is_running=False).order_by('run_order'):
            if task.last_run_at is None or now >= task.last_run_at + timedelta(minutes=task.interval_minutes):
                due_tasks.append(task)

        if not due_tasks:
            logger.debug("Heartbeat: no tasks due.")
            return

        # Step C — Execute due tasks
        for task in due_tasks:
            fn = TASK_FUNCTIONS.get(task.name)
            if fn is None:
                logger.warning("No function registered for task: %s — skipping", task.name)
                continue

            task.is_running = True
            task.last_run_at = now
            task.save(update_fields=['is_running', 'last_run_at'])

            try:
                fn()
                logger.info("Task completed: %s", task.name)
            except Exception:
                logger.exception("Task failed: %s", task.name)
            finally:
                task.is_running = False
                task.save(update_fields=['is_running'])
