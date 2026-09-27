from django.db import migrations


def add_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.get_or_create(
        name="reconcile_bid_outcomes",
        defaults={
            "interval_minutes": 60,
            "run_order": 10,
            "is_enabled": True,
            "is_running": False,
            "freeze_count": 0,
            "last_run_at": None,
        },
    )


def remove_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.filter(name="reconcile_bid_outcomes").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("quote", "0006_email_supplier"),
        ("core", "0003_seed_scheduled_tasks"),
    ]

    operations = [
        migrations.RunPython(add_task, remove_task),
    ]
