from unittest.mock import patch

from django.test import Client, TestCase, override_settings


@override_settings(REQUIRE_LOGIN=True)
class AzureHealthEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_azure_health_returns_200_when_db_ok(self):
        response = self.client.get("/api/azure-health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["checks"]["database"], "ok")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_azure_health_not_redirected_to_login(self):
        response = self.client.get("/api/azure-health/")
        self.assertNotEqual(response.status_code, 302)
        self.assertNotIn("/users/login", response.get("Location", ""))

    @patch("core.health.connection")
    def test_azure_health_returns_503_when_db_fails(self, mock_connection):
        mock_connection.cursor.side_effect = Exception("db down")
        response = self.client.get("/api/azure-health/")
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "unhealthy")
        self.assertEqual(data["checks"]["database"], "unavailable")

    def test_health_plain_returns_ok_when_db_ok(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "OK")
        self.assertEqual(response["Content-Type"], "text/plain")

    @patch("core.health.connection")
    def test_health_plain_returns_unavailable_when_db_fails(self, mock_connection):
        mock_connection.cursor.side_effect = Exception("db down")
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content.decode(), "UNAVAILABLE")

    def test_health_plain_not_redirected_to_login(self):
        response = self.client.get("/health/")
        self.assertNotEqual(response.status_code, 302)
