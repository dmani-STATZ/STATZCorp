from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from users.models import AppPermission, AppRegistry


@override_settings(REQUIRE_LOGIN=True)
class LoginRequiredMiddlewarePermissionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("perm_user", password="test-pass")
        self.quote_app = AppRegistry.objects.get(app_name="quote")
        self.quote_url = reverse("quote:dashboard")
        self.inventory_url = reverse("inventory:dashboard")
        self.permission_denied_path = reverse("permission_denied")

    def _assert_redirect_permission_denied(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.permission_denied_path)

    def test_registered_app_with_access_returns_200(self):
        AppPermission.objects.create(
            user=self.user, app_name=self.quote_app, has_access=True
        )
        self.client.force_login(self.user)
        response = self.client.get(self.quote_url)
        self.assertEqual(response.status_code, 200)

    def test_registered_app_with_access_false_redirects(self):
        AppPermission.objects.create(
            user=self.user, app_name=self.quote_app, has_access=False
        )
        self.client.force_login(self.user)
        response = self.client.get(self.quote_url)
        self._assert_redirect_permission_denied(response)

    def test_registered_app_without_permission_row_redirects(self):
        self.client.force_login(self.user)
        response = self.client.get(self.quote_url)
        self._assert_redirect_permission_denied(response)

    def test_unregistered_app_is_allowed(self):
        self.assertFalse(
            AppRegistry.objects.filter(app_name="inventory").exists(),
            "inventory must have no AppRegistry row for this test",
        )
        self.client.force_login(self.user)
        response = self.client.get(self.inventory_url)
        self.assertEqual(response.status_code, 200)

    @patch("STATZWeb.middleware.AppPermission.objects.get")
    def test_unexpected_error_redirects_and_logs(self, mock_get):
        mock_get.side_effect = RuntimeError("boom")
        self.client.force_login(self.user)
        with self.assertLogs("STATZWeb.middleware", level="ERROR") as logs:
            response = self.client.get(self.quote_url)
        self._assert_redirect_permission_denied(response)
        self.assertEqual(len(logs.records), 1)
        self.assertIn(self.quote_url, logs.records[0].getMessage())

    @patch("STATZWeb.middleware.AppPermission.objects.get")
    def test_database_error_redirects(self, mock_get):
        mock_get.side_effect = DatabaseError("db down")
        self.client.force_login(self.user)
        response = self.client.get(self.quote_url)
        self._assert_redirect_permission_denied(response)

    @patch("STATZWeb.middleware.AppPermission.objects.get")
    def test_superuser_bypasses_permission_check_on_error(self, mock_get):
        mock_get.side_effect = RuntimeError("boom")
        superuser = User.objects.create_superuser("su", password="test-pass")
        self.client.force_login(superuser)
        response = self.client.get(self.quote_url)
        self.assertEqual(response.status_code, 200)

    def test_unknown_url_returns_404_not_permission_denied(self):
        self.client.force_login(self.user)
        response = self.client.get("/definitely-not-a-route/")
        self.assertEqual(response.status_code, 404)

    @patch("STATZWeb.middleware.AppPermission.objects.get")
    def test_app_permission_multiple_objects_redirects(self, mock_get):
        mock_get.side_effect = AppPermission.MultipleObjectsReturned()
        self.client.force_login(self.user)
        response = self.client.get(self.quote_url)
        self._assert_redirect_permission_denied(response)
