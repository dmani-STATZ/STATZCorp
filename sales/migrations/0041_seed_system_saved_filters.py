# Data migration: seed SDVOSB and Research Pool system saved filters

from django.db import migrations


def seed_system_filters(apps, schema_editor):
    SavedFilter = apps.get_model("sales", "SavedFilter")
    SavedFilter.objects.get_or_create(
        name="SDVOSB",
        is_system=True,
        defaults={"filter_params": {"set_aside": "R"}, "user": None},
    )
    SavedFilter.objects.get_or_create(
        name="Research Pool",
        is_system=True,
        defaults={"filter_params": {"tab": "research"}, "user": None},
    )


def unseed_system_filters(apps, schema_editor):
    SavedFilter = apps.get_model("sales", "SavedFilter")
    SavedFilter.objects.filter(
        is_system=True,
        name__in=("SDVOSB", "Research Pool"),
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0040_savedfilter"),
    ]

    operations = [
        migrations.RunPython(seed_system_filters, unseed_system_filters),
    ]
