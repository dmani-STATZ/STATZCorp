from django.db import migrations


def add_dibbs_notices_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.get_or_create(
        name="check_dibbs_notices",
        defaults={
            "interval_minutes": 1440,
            "run_order": 7,
            "is_enabled": True,
            "is_running": False,
            "freeze_count": 0,
            "last_run_at": None,
        },
    )


def remove_dibbs_notices_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.filter(name="check_dibbs_notices").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0049_dibbsnotice"),
        ("core", "0003_seed_scheduled_tasks"),
    ]

    operations = [
        migrations.RunPython(add_dibbs_notices_task, remove_dibbs_notices_task),
    ]
