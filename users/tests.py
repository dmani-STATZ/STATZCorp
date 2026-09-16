from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(REQUIRE_LOGIN=False)
class PortalPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="portal-user", password="test")
        self.client.force_login(self.user)

    def test_calendar_page_renders(self):
        response = self.client.get(reverse("users:portal_calendar"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Natural-language scheduling")

    def test_resources_page_renders(self):
        response = self.client.get(reverse("users:portal_resources"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resources")

    def test_announcements_page_renders(self):
        response = self.client.get(reverse("users:portal_announcements"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Announcements")

    def test_dibbs_notices_page_renders(self):
        response = self.client.get(reverse("sales:dibbs_notices"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DIBBS Notices")
