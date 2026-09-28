"""
Seed the "Contract Administrators" group used as the fallback recipient list for
new-mod emails when a contract has no reviewer. Membership is managed in Django
admin after this; users 6 and 7 are the initial Contract Administrators.
"""
from django.conf import settings
from django.db import migrations

GROUP_NAME = "Contract Administrators"
INITIAL_USER_IDS = [6, 7]


def seed_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    # Materialize before writing (no MARS on SQL Server). Missing IDs are
    # skipped so dev/CI databases don't break.
    user_ids = list(
        User.objects.filter(pk__in=INITIAL_USER_IDS).values_list("pk", flat=True)
    )
    if user_ids:
        group.user_set.add(*user_ids)


class Migration(migrations.Migration):

    dependencies = [
        ('dibbs', '0004_dibbsawardmod_notified_at'),
        ('auth', '0012_alter_user_first_name_max_length'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(seed_group, migrations.RunPython.noop),
    ]
