from django.db import migrations


def seed_file_dfas_receipts(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.update_or_create(
        name="file_dfas_receipts",
        defaults={
            "interval_minutes": 15,
            "run_order": 11,
            "is_enabled": True,
            "is_running": False,
            "freeze_count": 0,
            "last_run_at": None,
        },
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_seed_reconcile_award_ledger_task"),
    ]

    operations = [
        migrations.RunPython(seed_file_dfas_receipts, noop_reverse),
    ]
