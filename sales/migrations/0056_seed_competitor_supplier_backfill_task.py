from django.db import migrations


def add_competitor_supplier_backfill_task(apps, schema_editor):
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


def remove_competitor_supplier_backfill_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.filter(name="run_competitor_supplier_backfill").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0055_competitor_award_supplier"),
        ("core", "0004_seed_reconcile_award_ledger_task"),
    ]

    operations = [
        migrations.RunPython(
            add_competitor_supplier_backfill_task,
            remove_competitor_supplier_backfill_task,
        ),
    ]
