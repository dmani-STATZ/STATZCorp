from django.db import migrations


def add_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.get_or_create(
        name="archive_stale_solicitations",
        defaults={
            "interval_minutes": 1440,
            "run_order": 9,
            "is_enabled": True,
            "is_running": False,
            "freeze_count": 0,
            "last_run_at": None,
        },
    )


def remove_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.filter(name="archive_stale_solicitations").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("quote", "0004_backfill_solicitation_state"),
        ("core", "0003_seed_scheduled_tasks"),
    ]

    operations = [
        migrations.RunPython(add_task, remove_task),
    ]
