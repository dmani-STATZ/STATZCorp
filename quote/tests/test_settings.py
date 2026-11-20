"""Quotes Settings: the registry / store, the test-recipient rule, the page, the banner and the status card."""
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from quote.models import QuoteSetting, QuoteSettingChange, QuoteSolicitation
from quote.services import app_settings
from quote.services.rfq import queue_rfqs
from quote.tests.test_outbound import TEST_ADDRESS, turn_on
from quote.tests.test_phase1 import Phase1Base
from suppliers.models import Contact, Supplier
from users.models import AppPermission, AppRegistry

TEST_ADDRESS = 'qa@statz.example'


class StoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'admin@example.com', 'x')

    def test_missing_row_is_the_default(self):
        self.assertIs(app_settings.get('rfq_test_mode'), False)
        self.assertEqual(app_settings.get('rfq_test_recipient'), '')
        self.assertIs(app_settings.get('email_scan_enabled'), False)

    def test_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            app_settings.get('not_a_key')
        with self.assertRaises(KeyError):
            app_settings.get_many(['rfq_test_mode', 'not_a_key'])
        with self.assertRaises(KeyError):
            app_settings.set_value('not_a_key', 'x', self.user)

    def test_set_value_writes_a_row_and_one_change(self):
        self.assertTrue(app_settings.set_value('rfq_test_recipient', ' QA@Statz.Example ', self.user))
        row = QuoteSetting.objects.get(key='rfq_test_recipient')
        self.assertEqual((row.value, row.updated_by), (TEST_ADDRESS, self.user))
        change = QuoteSettingChange.objects.get()
        self.assertEqual((change.key, change.old_value, change.new_value, change.changed_by),
                         ('rfq_test_recipient', '', TEST_ADDRESS, self.user))
        self.assertEqual(app_settings.get('rfq_test_recipient'), TEST_ADDRESS)

    def test_unchanged_value_writes_no_change_row(self):
        app_settings.set_value('rfq_test_recipient', TEST_ADDRESS, self.user)
        self.assertFalse(app_settings.set_value('rfq_test_recipient', TEST_ADDRESS.upper(), self.user))
        self.assertFalse(app_settings.set_value('rfq_test_mode', False, self.user))
        self.assertEqual(QuoteSettingChange.objects.count(), 1)
        self.assertFalse(QuoteSetting.objects.filter(key='rfq_test_mode').exists())

    def test_unavailable_setting_cannot_change(self):
        spec = app_settings.REGISTRY['rfq_test_mode']
        with patch.dict(app_settings.REGISTRY, {spec.key: replace(spec, available=False)}):
            with self.assertRaises(app_settings.SettingUnavailable):
                app_settings.set_value('rfq_test_mode', True, self.user)
        self.assertFalse(QuoteSetting.objects.exists())
        self.assertFalse(QuoteSettingChange.objects.exists())

    def test_code_only_setting_cannot_be_set_through_set_value(self):
        with self.assertRaises(app_settings.SettingInvalid):
            app_settings.set_value('email_scan_enabled_at', '2026-01-01T00:00:00+00:00', self.user)
        self.assertFalse(QuoteSetting.objects.exists())

    def test_bool_coercion(self):
        spec = app_settings.REGISTRY['rfq_test_mode']
        for raw, expected in (('true', 'true'), ('on', 'true'), ('1', 'true'), (True, 'true'),
                              ('false', 'false'), ('', 'false'), (None, 'false'), ('off', 'false')):
            self.assertEqual(app_settings._clean(spec, raw), expected, raw)

    def test_absent_checkbox_turns_the_switch_off(self):
        app_settings.save_section('rfqs', {'rfq_test_mode': 'on', 'rfq_test_recipient': TEST_ADDRESS}, self.user)
        self.assertIs(app_settings.get('rfq_test_mode'), True)
        result = app_settings.save_section('rfqs', {'rfq_test_recipient': TEST_ADDRESS}, self.user)
        self.assertTrue(result.ok)
        self.assertIs(app_settings.get('rfq_test_mode'), False)

    def test_test_mode_needs_a_valid_recipient(self):
        with self.assertRaises(app_settings.SettingInvalid):
            app_settings.set_value('rfq_test_mode', True, self.user)
        self.assertFalse(QuoteSetting.objects.exists())

    def test_save_section_is_all_or_nothing(self):
        result = app_settings.save_section('rfqs', {'rfq_test_mode': 'on', 'rfq_test_recipient': 'a@x.com,b@x.com'}, self.user)
        self.assertFalse(result.ok)
        self.assertIn('rfq_test_recipient', result.errors)
        self.assertFalse(QuoteSetting.objects.exists())
        self.assertFalse(QuoteSettingChange.objects.exists())

        result = app_settings.save_section('rfqs', {'rfq_test_mode': 'on', 'rfq_test_recipient': ''}, self.user)
        self.assertFalse(result.ok)
        self.assertFalse(QuoteSetting.objects.exists())

    def test_save_section_turns_on_and_off_in_one_post(self):
        result = app_settings.save_section('rfqs', {'rfq_test_mode': 'on', 'rfq_test_recipient': TEST_ADDRESS}, self.user)
        self.assertTrue(result.ok)
        self.assertEqual(sorted(result.changed), ['rfq_test_mode', 'rfq_test_recipient'])
        result = app_settings.save_section('rfqs', {'rfq_test_recipient': ''}, self.user)
        self.assertTrue(result.ok)
        self.assertEqual(app_settings.get_many(['rfq_test_mode', 'rfq_test_recipient']),
                         {'rfq_test_mode': False, 'rfq_test_recipient': ''})

    def test_forged_post_for_a_code_only_setting_changes_nothing(self):
        result = app_settings.save_section('email_scan', {
            'email_scan_enabled_at': '2020-01-01T00:00:00+00:00', 'sonnet_daily_cap': '10',
        }, self.user)
        self.assertFalse(result.ok)
        self.assertEqual(result.errors['email_scan_enabled_at'], app_settings.NOT_EDITABLE_MESSAGE)
        self.assertFalse(QuoteSetting.objects.exists())

    def test_unknown_section(self):
        self.assertFalse(app_settings.save_section('nope', {}, self.user).ok)

    def test_get_many_is_one_query(self):
        app_settings.set_value('rfq_test_recipient', TEST_ADDRESS, self.user)
        with self.assertNumQueries(1):
            values = app_settings.get_many(list(app_settings.REGISTRY))
        self.assertEqual(values, {'email_scan_enabled': False, 'email_scan_enabled_at': None,
                                  'jev_min_quote_probability': Decimal('0.20'),
                                  'jev_block_hold_probability': Decimal('0.50'), 'sonnet_daily_cap': 150,
                                  'rfq_test_mode': False, 'rfq_test_recipient': TEST_ADDRESS})


class TestRecipientTests(TestCase):
    def test_accepts_a_normal_address(self):
        self.assertIsNone(app_settings.validate_test_recipient(TEST_ADDRESS))
        self.assertIsNone(app_settings.validate_test_recipient(' QA@Statz.Example '))

    def test_rejects_blank_lists_spaces_and_malformed(self):
        for bad in ('', '   ', None, 'a@x.com,b@x.com', 'a@x.com; b@x.com', 'a @x.com', 'a@x.com b@x.com',
                    'not-an-email', 'a@', '@x.com'):
            self.assertIsNotNone(app_settings.validate_test_recipient(bad), bad)

    def test_rejects_every_supplier_directory_address_case_insensitively(self):
        supplier = Supplier.objects.create(
            name='Vortex', business_email='Biz@Vortex.example', primary_email='Primary@Vortex.example',
            rfq_email='RFQ@Vortex.example',
        )
        Contact.objects.create(name='Pat', email='Pat@Vortex.example', supplier=supplier)
        Contact.objects.create(name='Loose', email='Loose@Other.example')
        for address in ('biz@vortex.example', 'PRIMARY@VORTEX.EXAMPLE', 'rfq@vortex.example',
                        'pat@vortex.example', 'loose@other.example'):
            error = app_settings.validate_test_recipient(address)
            self.assertIsNotNone(error, address)
            self.assertIn('supplier or contact', error)


@override_settings(REQUIRE_LOGIN=True)
class SettingsAccessTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser('boss', 'boss@example.com', 'x')
        self.rep = User.objects.create_user('rep', password='x')
        AppPermission.objects.create(
            user=self.rep, app_name=AppRegistry.objects.get(app_name='quote'), has_access=True,
        )

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get(reverse('quote:settings'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('users:login'), resp.url)
        resp = self.client.post(reverse('quote:settings_save'), {'section': 'rfqs'})
        self.assertEqual(resp.status_code, 302)

    def test_a_quotes_user_who_is_not_a_superuser_gets_403_and_no_link(self):
        self.client.force_login(self.rep)
        self.assertEqual(self.client.get(reverse('quote:settings')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('quote:settings_save'), {'section': 'rfqs', 'rfq_test_mode': 'on'}).status_code,
            403,
        )
        page = self.client.get(reverse('quote:dashboard'))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, reverse('quote:settings'))
        self.assertFalse(QuoteSetting.objects.exists())

    def test_superuser_sees_the_page_the_link_and_the_live_switch(self):
        self.client.force_login(self.superuser)
        page = self.client.get(reverse('quote:settings'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="email_scan_enabled"')
        self.assertContains(page, 'name="confirm_scan_on"')
        self.assertContains(page, 'name="jev_min_quote_probability"')
        self.assertNotContains(page, 'name="email_scan_enabled_at"')
        self.assertContains(self.client.get(reverse('quote:dashboard')), reverse('quote:settings'))

    def test_turning_scanning_on_without_the_confirmation_changes_nothing(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(reverse('quote:settings_save'), {
            'section': 'email_scan', 'email_scan_enabled': 'on',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, app_settings.CONFIRM_SCAN_MESSAGE)
        self.assertFalse(QuoteSetting.objects.exists())

    def test_a_bad_recipient_is_rejected_and_nothing_is_saved(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(reverse('quote:settings_save'), {
            'section': 'rfqs', 'rfq_test_mode': 'on', 'rfq_test_recipient': 'not-an-email',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Enter a valid email address.')
        self.assertFalse(QuoteSetting.objects.exists())

    def test_a_good_save_redirects(self):
        self.client.force_login(self.superuser)
        resp = self.client.post(reverse('quote:settings_save'), {
            'section': 'rfqs', 'rfq_test_mode': 'on', 'rfq_test_recipient': TEST_ADDRESS,
        })
        self.assertRedirects(resp, reverse('quote:settings'))
        self.assertIs(app_settings.get('rfq_test_mode'), True)


class ChromeTests(Phase1Base):
    def _queue(self):
        QuoteSolicitation.objects.filter(solicitation=self.sol).update(status='MATCHED')
        queue_rfqs(self.sol, [self.supplier], self.user)

    def test_banner_and_send_labels(self):
        self._queue()
        off = self.client.get(reverse('quote:rfq_queue'))
        self.assertNotContains(off, 'TEST MODE ON')
        self.assertNotContains(off, 'Send TEST')
        self.assertContains(off, 'Send all (')
        turn_on()
        on = self.client.get(reverse('quote:rfq_queue'))
        self.assertContains(on, f'TEST MODE ON — RFQs and packhouse requests go to {TEST_ADDRESS}')
        self.assertContains(on, 'Send TEST')
        self.assertContains(on, 'Send all TEST')
        self.assertContains(on, 'Real recipients:')
        mailbox = self.client.get(reverse('quote:mailbox'))
        self.assertEqual(mailbox.status_code, 200)
        self.assertContains(mailbox, 'TEST MODE ON')

    def test_the_banner_swallows_an_exception(self):
        turn_on()
        with patch('quote.templatetags.quote_tags.test_mode_state', side_effect=RuntimeError('boom')):
            resp = self.client.get(reverse('quote:rfq_queue'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'TEST MODE ON')


class StatusCardTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser('boss', 'boss@example.com', 'x'))

    @override_settings(TYPESAFE_API_KEY='SENTINEL-KEY-DO-NOT-RENDER-9f3a', TYPESAFE_ENABLED=True)
    def test_the_page_never_contains_the_api_key(self):
        resp = self.client.get(reverse('quote:settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'SENTINEL-KEY-DO-NOT-RENDER-9f3a')
        self.assertContains(resp, 'API key present: yes')
        self.assertContains(resp, 'TypeSafe is on')

    def _page_survives(self, target):
        with patch(target, side_effect=RuntimeError('down')):
            resp = self.client.get(reverse('quote:settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'unavailable')
        return resp

    def test_each_status_line_fails_on_its_own(self):
        resp = self._page_survives('quote.services.app_settings._typesafe_status')
        self.assertContains(resp, 'Anthropic budget')
        self.assertNotContains(resp, 'TypeSafe is')

        resp = self._page_survives('quote.services.app_settings._budget_status')
        self.assertContains(resp, 'API key present:')

        resp = self._page_survives('quote.services.app_settings._worker_status')
        self.assertContains(resp, 'API key present:')

        resp = self._page_survives('quote.services.app_settings._quote_tasks_status')
        self.assertContains(resp, 'API key present:')
        self.assertNotContains(resp, 'archive_stale_solicitations')
