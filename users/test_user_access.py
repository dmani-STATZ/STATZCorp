from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from training.models import Account, Course, Matrix, Tracker, UserAccount
from users.azure_auth import MicrosoftAuthBackend
from users.models import AppPermission, AppRegistry, UserOAuthToken

MS_BACKEND = "users.azure_auth.MicrosoftAuthBackend"


@override_settings(REQUIRE_LOGIN=True)
class UserAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root", "root@example.com", "pw")
        self.quote = AppRegistry.objects.get(app_name="quote")
        self.cui = Account.objects.create(type="cui_user")
        self.user = User.objects.create_user("worker", "worker@example.com", "pw")
        AppPermission.objects.create(user=self.user, app_name=self.quote, has_access=True)

    # --- authorization ---------------------------------------------------

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("users:user_access"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response.url)

    def test_non_superuser_denied_on_every_view(self):
        staff = User.objects.create_user("staffer", "s@example.com", "pw", is_staff=True)
        self.client.force_login(staff)
        for name, args in [
            ("users:user_access", []),
            ("users:user_access_create", []),
            ("users:user_access_edit", [self.user.pk]),
        ]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        response = self.client.post(reverse("users:user_access_disable", args=[self.user.pk]))
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            reverse("users:user_access_create"), {"email": "evil@example.com"}
        )
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertFalse(User.objects.filter(email="evil@example.com").exists())

    def test_disable_requires_post(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("users:user_access_disable", args=[self.user.pk]))
        self.assertEqual(response.status_code, 405)

    def test_settings_modal_link_only_for_superuser(self):
        url = reverse("users:user_access")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("users:portal_calendar")), url)
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("users:portal_calendar")), url)

    # --- list / create / edit -------------------------------------------

    def test_list_renders_and_searches(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("users:user_access"), {"q": "worker"})
        self.assertContains(response, "worker@example.com")
        self.assertNotContains(response, "root@example.com")

    def test_create_standard_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("users:user_access_create"),
            {
                "email": "new.person@example.com",
                "first_name": "New",
                "is_staff": "on",
                "last_name": "Person",
                "apps": [self.quote.pk],
                "training_accounts": [self.cui.pk],
            },
        )
        user = User.objects.get(email="new.person@example.com")
        self.assertRedirects(response, reverse("users:user_access_edit", args=[user.pk]))
        self.assertEqual(user.username, "new.person")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        self.assertTrue(
            AppPermission.objects.filter(user=user, app_name=self.quote, has_access=True).exists()
        )
        self.assertTrue(UserAccount.objects.filter(user=user, account=self.cui).exists())

    def test_create_rejects_duplicate_email_case_insensitive(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:user_access_create"), {"email": "WORKER@example.com"})
        self.assertEqual(User.objects.filter(email__iexact="worker@example.com").count(), 1)

    def test_revoking_grant_denies_next_request(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("quote:dashboard")).status_code, 200)

        self.client.force_login(self.admin)
        self.client.post(
            reverse("users:user_access_edit", args=[self.user.pk]),
            {"email": self.user.email},
        )
        self.assertFalse(AppPermission.objects.filter(user=self.user).exists())

        self.client.force_login(self.user)
        response = self.client.get(reverse("quote:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("permission_denied"))

    def test_removing_training_type_keeps_history(self):
        course = Course.objects.create(name="CUI basics")
        matrix = Matrix.objects.create(course=course, account=self.cui, frequency="once")
        UserAccount.objects.create(user=self.user, account=self.cui)
        Tracker.objects.create(user=self.user, matrix=matrix)

        self.client.force_login(self.admin)
        self.client.post(
            reverse("users:user_access_edit", args=[self.user.pk]),
            {"email": self.user.email, "apps": [self.quote.pk]},
        )
        self.assertFalse(UserAccount.objects.filter(user=self.user).exists())
        self.assertEqual(Tracker.objects.filter(user=self.user).count(), 1)

    # --- disable / reactivate -------------------------------------------

    def test_disable_ends_existing_microsoft_session_and_keeps_grants(self):
        UserOAuthToken.objects.create(user=self.user, provider="microsoft", access_token="t")
        user_client = self.client_class()
        user_client.force_login(self.user, backend=MS_BACKEND)
        session = user_client.session
        session["microsoft_auth_success"] = True
        session.save()
        self.assertEqual(user_client.get(reverse("quote:dashboard")).status_code, 200)

        self.client.force_login(self.admin)
        self.client.post(reverse("users:user_access_disable", args=[self.user.pk]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(AppPermission.objects.filter(user=self.user).exists())
        self.assertFalse(UserOAuthToken.objects.filter(user=self.user).exists())

        response = user_client.get(reverse("quote:dashboard"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.resolver_match.view_name, "users:login")
        self.assertNotIn("microsoft_auth_success", user_client.session)

    def test_disable_ends_existing_password_session(self):
        user_client = self.client_class()
        user_client.force_login(self.user, backend="django.contrib.auth.backends.ModelBackend")
        self.client.force_login(self.admin)
        self.client.post(reverse("users:user_access_disable", args=[self.user.pk]))
        response = user_client.get(reverse("quote:dashboard"))
        self.assertIn(reverse("users:login"), response.url)

    def test_cannot_disable_self_or_last_superuser(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:user_access_disable", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

        from users import user_access

        other = User.objects.create_superuser("root2", "root2@example.com", "pw")
        user_access.disable_user(other, self.admin)  # two active supers -> allowed
        with self.assertRaises(user_access.UserAccessError):
            user_access.disable_user(self.admin, other)  # other is now the last one
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_reactivate_restores_grants(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("users:user_access_disable", args=[self.user.pk]))
        response = self.client.post(
            reverse("users:user_access_reactivate", args=[self.user.pk]), follow=True
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertContains(response, self.quote.display_name)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("quote:dashboard")).status_code, 200)

    # --- sign-in paths ---------------------------------------------------

    def test_microsoft_signin_refused_for_disabled_user(self):
        self.user.is_active = False
        self.user.save()
        token = {
            "access_token": "abc",
            "id_token_claims": {"email": f" {self.user.email.upper()} ", "name": "W K", "oid": "1"},
        }
        request = RequestFactory().get("/")
        with patch.object(MicrosoftAuthBackend, "get_microsoft_auth_token", return_value=token):
            result = MicrosoftAuthBackend().authenticate(request, auth_code="code")
        self.assertIsNone(result)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "")
        self.assertFalse(UserOAuthToken.objects.filter(user=self.user).exists())
        self.assertEqual(User.objects.filter(email=self.user.email).count(), 1)

    def test_microsoft_signin_matches_provisioned_user(self):
        token = {
            "access_token": "abc",
            "id_token_claims": {"email": f" {self.user.email.upper()} ", "name": "W K", "oid": "1"},
        }
        request = RequestFactory().get("/")
        request.session = {}
        with patch.object(MicrosoftAuthBackend, "get_microsoft_auth_token", return_value=token):
            result = MicrosoftAuthBackend().authenticate(request, auth_code="code")
        self.assertEqual(result, self.user)

    def test_microsoft_signin_refuses_ambiguous_email(self):
        User.objects.create_user("duplicate", self.user.email.upper())
        token = {
            "access_token": "abc",
            "id_token_claims": {"email": self.user.email, "name": "W K", "oid": "1"},
        }
        with patch.object(MicrosoftAuthBackend, "get_microsoft_auth_token", return_value=token):
            result = MicrosoftAuthBackend().authenticate(RequestFactory().get("/"), auth_code="code")
        self.assertIsNone(result)
        self.assertFalse(UserOAuthToken.objects.filter(user__email__iexact=self.user.email).exists())

    def test_oauth_password_set_requires_authenticated_owner(self):
        session = self.client.session
        session["oauth_migration_user_id"] = self.user.pk
        session.save()
        response = self.client.post(
            reverse("users:oauth_password_set"),
            {"new_password1": "longpassword1", "new_password2": "longpassword1"},
        )
        self.assertRedirects(response, reverse("users:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_invalid_account_fields_are_rejected(self):
        self.client.force_login(self.admin)
        for fields in (
            {"email": "invalid-email"},
            {"email": "new@example.com", "username": "invalid username"},
            {"email": "new@example.com", "first_name": "x" * 151},
        ):
            with self.subTest(fields=fields):
                response = self.client.post(reverse("users:user_access_create"), fields)
                self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email__in=["invalid-email", "new@example.com"]).exists())

    @override_settings(REQUIRE_LOGIN=False)
    def test_superuser_gate_does_not_depend_on_middleware(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("users:user_access")).status_code, 403)
        self.assertEqual(self.client.post(reverse("users:user_access_create")).status_code, 403)

    def test_training_entry_follows_registered_grant(self):
        training, _ = AppRegistry.objects.get_or_create(
            app_name="training", defaults={"display_name": "Training"}
        )
        self.client.force_login(self.user)
        url = reverse("training:dashboard")
        self.assertRedirects(self.client.get(url), reverse("permission_denied"))
        AppPermission.objects.create(user=self.user, app_name=training, has_access=True)
        self.assertEqual(self.client.get(url).status_code, 200)
        AppPermission.objects.filter(user=self.user, app_name=training).delete()
        self.assertRedirects(self.client.get(url), reverse("permission_denied"))

    @override_settings(REQUIRE_LOGIN=False)
    def test_training_grant_does_not_allow_management(self):
        self.client.force_login(self.user)
        for name, args in (
            ("manage_matrix", []),
            ("manage_matrix_for_account", [self.cui.pk]),
            ("add_arctic_wolf_course", []),
            ("arctic_wolf_course_list", []),
            ("arctic_wolf_email_preview", ["example"]),
            ("arctic_wolf_email_eml", ["example"]),
        ):
            with self.subTest(view=name):
                url = reverse(f"training:{name}", args=args)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url).status_code, 403)

    @override_settings(REQUIRE_LOGIN=False)
    def test_certificate_download_requires_owner_or_privileged_role(self):
        course = Course.objects.create(name="CUI basics")
        matrix = Matrix.objects.create(course=course, account=self.cui, frequency="once")
        tracker = Tracker.objects.create(
            user=self.user, matrix=matrix, document=b"certificate", document_name="cert.pdf"
        )
        other = User.objects.create_user("other", "other@example.com")
        url = reverse("training:view_document", args=[tracker.pk])
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).content, b"certificate")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).content, b"certificate")
