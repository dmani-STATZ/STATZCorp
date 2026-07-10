from django.db import migrations


def remove_competitor_supplier_backfill_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.filter(name="run_competitor_supplier_backfill").delete()


def restore_competitor_supplier_backfill_task(apps, schema_editor):
    """Rollback only — recreates the 0056 seed values."""
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.get_or_create(
        name="run_competitor_supplier_backfill",
        defaults={
            "interval_minutes": 15,
            "run_order": 9,
            "is_enabled": True,
            "is_running": False,
            "freeze_count": 0,
            "last_run_at": None,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0057_replace_competitor_award_supplier_with_entities"),
        ("core", "0004_seed_reconcile_award_ledger_task"),
    ]

    operations = [
        migrations.RunPython(
            remove_competitor_supplier_backfill_task,
            restore_competitor_supplier_backfill_task,
        ),
    ]
