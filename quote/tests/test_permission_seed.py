"""
The 0002 data migration is this app's access-control switch: it flips `quote`
from fail-open to deny-by-default and grants it to whoever already has `sales`.

These tests call the migration functions directly with the real app registry,
which is what we actually care about -- that the audience is copied correctly
and that the reverse restores fail-open.
"""
import importlib

from django.apps import apps as global_apps
from django.contrib.auth.models import User
from django.test import TestCase

from users.models import AppPermission, AppRegistry

_migration = importlib.import_module(
    'quote.migrations.0002_seed_app_registry_and_permissions'
)
seed = _migration.seed_registry_and_permissions
unseed = _migration.unseed_registry_and_permissions


class PermissionSeedTests(TestCase):
    def setUp(self):
        # The migration ran during test-db setup; start each test from a clean
        # slate so the seeding logic itself is what's under test.
        AppPermission.objects.all().delete()
        AppRegistry.objects.all().delete()

        self.sales_app = AppRegistry.objects.create(
            app_name='sales', display_name='Sales (DIBBS Bidding)', is_active=True,
        )
        self.granted = User.objects.create_user('rep_with_sales')
        self.denied = User.objects.create_user('rep_denied_sales')
        self.unrelated = User.objects.create_user('rep_no_sales_row')

        AppPermission.objects.create(
            user=self.granted, app_name=self.sales_app, has_access=True,
        )
        AppPermission.objects.create(
            user=self.denied, app_name=self.sales_app, has_access=False,
        )

    def _quote_grantees(self):
        quote_app = AppRegistry.objects.get(app_name='quote')
        return set(
            AppPermission.objects.filter(app_name=quote_app, has_access=True)
            .values_list('user__username', flat=True)
        )

    def test_seed_registers_the_quote_app(self):
        seed(global_apps, None)

        row = AppRegistry.objects.get(app_name='quote')
        self.assertEqual(row.display_name, 'Quotes (DIBBS Quoting)')
        self.assertTrue(row.is_active)

    def test_seed_grants_only_users_with_sales_access(self):
        seed(global_apps, None)

        self.assertEqual(self._quote_grantees(), {'rep_with_sales'})

    def test_seed_does_not_grant_users_explicitly_denied_sales(self):
        seed(global_apps, None)

        quote_app = AppRegistry.objects.get(app_name='quote')
        self.assertFalse(
            AppPermission.objects.filter(
                user=self.denied, app_name=quote_app,
            ).exists()
        )

    def test_seed_is_idempotent(self):
        seed(global_apps, None)
        seed(global_apps, None)

        quote_app = AppRegistry.objects.get(app_name='quote')
        self.assertEqual(
            AppPermission.objects.filter(app_name=quote_app).count(), 1,
        )

    def test_seed_without_a_sales_registry_row_grants_nobody(self):
        # Registry row must still appear (deny-by-default) rather than guessing
        # an audience.
        self.sales_app.delete()

        seed(global_apps, None)

        self.assertTrue(AppRegistry.objects.filter(app_name='quote').exists())
        self.assertEqual(self._quote_grantees(), set())

    def test_unseed_restores_fail_open_and_leaves_sales_alone(self):
        seed(global_apps, None)
        unseed(global_apps, None)

        self.assertFalse(AppRegistry.objects.filter(app_name='quote').exists())
        self.assertTrue(
            AppPermission.objects.filter(
                user=self.granted, app_name=self.sales_app, has_access=True,
            ).exists()
        )

    def test_unseed_is_safe_when_never_seeded(self):
        unseed(global_apps, None)  # must not raise

        self.assertFalse(AppRegistry.objects.filter(app_name='quote').exists())
