from django.db import migrations

SEED_TASKS = [
    {"name": "send_queued_rfqs", "interval_minutes": 5, "run_order": 1},
    {"name": "poll_we_won_today", "interval_minutes": 15, "run_order": 2},
    {"name": "sync_sharepoint_calendar", "interval_minutes": 60, "run_order": 3},
    {"name": "dispatch_campaigns", "interval_minutes": 10, "run_order": 4},
    {"name": "process_ai_snippets", "interval_minutes": 5, "run_order": 5},
    {"name": "dispatch_followups", "interval_minutes": 10, "run_order": 6},
]


def seed_scheduled_tasks(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    for task in SEED_TASKS:
        ScheduledTask.objects.get_or_create(
            name=task["name"],
            defaults={
                "interval_minutes": task["interval_minutes"],
                "run_order": task["run_order"],
                "is_enabled": True,
                "is_running": False,
                "freeze_count": 0,
                "last_run_at": None,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_scheduled_task"),
    ]

    operations = [
        migrations.RunPython(seed_scheduled_tasks, migrations.RunPython.noop),
    ]
