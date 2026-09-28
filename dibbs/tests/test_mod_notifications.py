"""
Tests for new-mod email notifications (dibbs.services.mod_notifications).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from contracts.models import Company, Contract
from dibbs.models import DibbsAward, DibbsAwardMod
from dibbs.services.contract_mods import match_new_mods_after_import
from dibbs.services.mod_notifications import (
    CONTRACT_ADMIN_GROUP,
    notify_new_mods,
    recipients_for_contract,
)

User = get_user_model()

SEND_PATH = "mailer.services.graph_mail.send_mail_via_graph"


@override_settings(GRAPH_MAIL_ENABLED=True, APP_BASE_URL="https://statz.test")
class ModNotificationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Notify Co", slug="notify-co", is_active=True
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number="SPE4A6-26-P-T630",
        )
        self.award = DibbsAward.objects.create(
            sol_number="SOL1",
            notice_id="N1",
            award_date=date.today(),
            award_basic_number="SPE4A626PT630",
        )
        self.group, _ = Group.objects.get_or_create(name=CONTRACT_ADMIN_GROUP)
        self.admin_a = User.objects.create_user("admin_a", email="a@statz.test")
        self.admin_b = User.objects.create_user("admin_b", email="b@statz.test")
        self.admin_inactive = User.objects.create_user(
            "admin_c", email="c@statz.test", is_active=False
        )
        self.admin_no_email = User.objects.create_user("admin_d", email="")
        self.group.user_set.add(
            self.admin_a, self.admin_b, self.admin_inactive, self.admin_no_email
        )

    def _mod(self, nsn="1234567890123", price="100.00", **kwargs):
        return DibbsAwardMod.objects.create(
            award=self.award,
            award_basic_number="SPE4A626PT630",
            awardee_cage="64W95",  # partner CAGE — always in the matching gate
            mod_date=date.today(),
            nsn=nsn,
            mod_contract_price=Decimal(price),
            **kwargs,
        )

    # --- recipients ---------------------------------------------------------

    def test_reviewer_only_when_set(self):
        reviewer = User.objects.create_user("rev", email="rev@statz.test")
        self.contract.reviewed_by = reviewer
        self.contract.save()
        self.assertEqual(recipients_for_contract(self.contract), ["rev@statz.test"])

    def test_falls_back_to_active_group_members_with_email(self):
        self.assertEqual(
            sorted(recipients_for_contract(self.contract)),
            ["a@statz.test", "b@statz.test"],
        )

    def test_falls_back_when_reviewer_inactive(self):
        reviewer = User.objects.create_user(
            "rev", email="rev@statz.test", is_active=False
        )
        self.contract.reviewed_by = reviewer
        self.contract.save()
        self.assertNotIn("rev@statz.test", recipients_for_contract(self.contract))

    # --- sending ------------------------------------------------------------

    def test_reviewer_gets_single_email(self):
        reviewer = User.objects.create_user("rev", email="rev@statz.test")
        self.contract.reviewed_by = reviewer
        self.contract.save()
        mod = self._mod(matched_contract=self.contract)

        with mock.patch(SEND_PATH, return_value=True) as send:
            self.assertEqual(notify_new_mods([mod.pk]), 1)

        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["to_address"], "rev@statz.test")
        self.assertEqual(kwargs["cc_addresses"], [])
        self.assertIn("SPE4A6-26-P-T630", kwargs["subject"])
        self.assertIn(f"https://statz.test/contracts/{self.contract.pk}/detail/", kwargs["body"])
        self.assertTrue(kwargs["is_html"])

    def test_one_email_per_contract_and_stamps_notified_at(self):
        m1 = self._mod(nsn="1111111111111", matched_contract=self.contract)
        m2 = self._mod(nsn="2222222222222", matched_contract=self.contract)

        with mock.patch(SEND_PATH, return_value=True) as send:
            self.assertEqual(notify_new_mods([m1.pk, m2.pk]), 1)

        send.assert_called_once()
        m1.refresh_from_db()
        m2.refresh_from_db()
        self.assertIsNotNone(m1.notified_at)
        self.assertIsNotNone(m2.notified_at)

    def test_already_notified_is_skipped(self):
        mod = self._mod(matched_contract=self.contract)
        with mock.patch(SEND_PATH, return_value=True) as send:
            notify_new_mods([mod.pk])
            notify_new_mods([mod.pk])
        send.assert_called_once()

    def test_send_failure_leaves_notified_at_null(self):
        mod = self._mod(matched_contract=self.contract)
        with mock.patch(SEND_PATH, return_value=False):
            self.assertEqual(notify_new_mods([mod.pk]), 0)
        mod.refresh_from_db()
        self.assertIsNone(mod.notified_at)

    @override_settings(GRAPH_MAIL_ENABLED=False)
    def test_disabled_sends_nothing(self):
        mod = self._mod(matched_contract=self.contract)
        with mock.patch(SEND_PATH) as send:
            self.assertEqual(notify_new_mods([mod.pk]), 0)
        send.assert_not_called()

    # --- hook in the matching process --------------------------------------

    def test_match_new_mods_after_import_sends_email(self):
        mod = self._mod()
        with mock.patch(SEND_PATH, return_value=True) as send:
            matched = match_new_mods_after_import(before_max_mod_id=mod.pk - 1)
        self.assertEqual(matched, 1)
        send.assert_called_once()

    def test_notification_error_does_not_break_matching(self):
        mod = self._mod()
        with mock.patch(SEND_PATH, side_effect=RuntimeError("boom")), mock.patch(
            "dibbs.services.mod_notifications.recipients_for_contract",
            side_effect=RuntimeError("boom"),
        ):
            matched = match_new_mods_after_import(before_max_mod_id=mod.pk - 1)
        mod.refresh_from_db()
        self.assertEqual(matched, 1)
        self.assertEqual(mod.matched_contract_id, self.contract.id)
        self.assertIsNone(mod.notified_at)
