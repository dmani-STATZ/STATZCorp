from django.db import migrations


def add_reconcile_award_ledger_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.get_or_create(
        name="reconcile_award_ledger",
        defaults={
            "interval_minutes": 1440,
            "run_order": 8,
            "is_enabled": True,
            "is_running": False,
            "freeze_count": 0,
            "last_run_at": None,
        },
    )


def remove_reconcile_award_ledger_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.filter(name="reconcile_award_ledger").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_seed_scheduled_tasks"),
        ("intake", "0003_award_ledger"),
    ]

    operations = [
        migrations.RunPython(
            add_reconcile_award_ledger_task,
            remove_reconcile_award_ledger_task,
        ),
    ]
