"""
Register the `quote` app in users.AppRegistry and grant it to everyone who
already has access to `sales`.

Why this matters: STATZWeb.middleware.LoginRequiredMiddleware resolves the URL
namespace and looks it up in AppRegistry. With NO row the app is fail-open --
every authenticated user gets in. Once a row exists it is deny-by-default, and
each non-superuser needs an explicit AppPermission(has_access=True). Nothing
backfills those (the auto-seed signal in users/signals.py is commented out), so
the grant has to happen here.

`quote` replaces the sales DIBBS workflow, so the audience is the same people.

MSSQL/pyodbc note: no MARS. Every read is materialized with list(...values())
before any write, and writes are batched inside transaction.atomic().
"""
from django.db import migrations, transaction

BATCH_SIZE = 500

QUOTE_APP_NAME = 'quote'
QUOTE_DISPLAY_NAME = 'Quotes (DIBBS Quoting)'
SOURCE_APP_NAME = 'sales'


def seed_registry_and_permissions(apps, schema_editor):
    AppRegistry = apps.get_model('users', 'AppRegistry')
    AppPermission = apps.get_model('users', 'AppPermission')

    quote_app, _ = AppRegistry.objects.update_or_create(
        app_name=QUOTE_APP_NAME,
        defaults={'display_name': QUOTE_DISPLAY_NAME, 'is_active': True},
    )

    sales_app = AppRegistry.objects.filter(app_name=SOURCE_APP_NAME).first()
    if sales_app is None:
        # No sales registry row means permissions were never configured for the
        # DIBBS workflow. Leave the quote row in place (deny-by-default) and let
        # an admin grant access explicitly rather than guessing an audience.
        return

    # Materialize both sides before writing anything.
    granted_user_ids = list(
        AppPermission.objects.filter(
            app_name=sales_app, has_access=True,
        ).values_list('user_id', flat=True)
    )
    already_have_quote = set(
        AppPermission.objects.filter(app_name=quote_app)
        .values_list('user_id', flat=True)
    )

    to_create = [
        AppPermission(user_id=uid, app_name=quote_app, has_access=True)
        for uid in granted_user_ids
        if uid not in already_have_quote
    ]

    for start in range(0, len(to_create), BATCH_SIZE):
        with transaction.atomic():
            for permission in to_create[start:start + BATCH_SIZE]:
                permission.save()


def unseed_registry_and_permissions(apps, schema_editor):
    """
    Remove the quote permissions and registry row, restoring fail-open access.
    Deliberately deletes only quote rows -- sales permissions are untouched.
    """
    AppRegistry = apps.get_model('users', 'AppRegistry')
    AppPermission = apps.get_model('users', 'AppPermission')

    quote_app = AppRegistry.objects.filter(app_name=QUOTE_APP_NAME).first()
    if quote_app is None:
        return

    AppPermission.objects.filter(app_name=quote_app).delete()
    quote_app.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('quote', '0001_initial'),
        ('users', '0014_rename_users_relea_publish_0ab0ec_idx_users_relea_publish_2d1cf3_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(
            seed_registry_and_permissions,
            unseed_registry_and_permissions,
        ),
    ]
