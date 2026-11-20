from django.db import migrations


def add_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.get_or_create(
        name="process_quote_email_pipeline",
        defaults={
            "interval_minutes": 5,
            "run_order": 12,
            "is_enabled": True,
            "is_running": False,
            "freeze_count": 0,
            "last_run_at": None,
        },
    )


def remove_task(apps, schema_editor):
    ScheduledTask = apps.get_model("core", "ScheduledTask")
    ScheduledTask.objects.filter(name="process_quote_email_pipeline").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("quote", "0014_email_pipeline"),
        ("core", "0003_seed_scheduled_tasks"),
    ]

    operations = [
        migrations.RunPython(add_task, remove_task),
    ]
