"""Mailbox scan queue, block sender, release hold, and detail fragment UI."""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import ScheduledTask
from quote.models import QuoteEmail, QuoteEmailScan, QuoteEmailTriage, QuoteSenderBlock
from quote.services import app_settings, blocklist, email_scan, email_triage
from quote.tests.pipeline_fixtures import CALL, PipelineBase
from quote.tests.test_email_scan import ScanBase, echelon, reply
from users.models import AppPermission, AppRegistry

BLOCKED = 'This sender is blocked, so the email cannot be scanned.'
XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class ScanPostTests(ScanBase):
    def post_scan(self, email=None):
        return self.client.post(reverse('quote:email_scan', args=[(email or self.email).pk]))

    def test_post_queues_deep_manual_scan(self):
        with patch(CALL) as call:
            resp = self.post_scan()
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body['created'])
        call.assert_not_called()
        scan = QuoteEmailScan.objects.get()
        self.assertEqual((scan.trigger, scan.status, scan.level), ('manual', 'queued', 'deep'))

    def test_second_post_reuses_active_scan(self):
        self.post_scan()
        with patch(CALL) as call:
            resp = self.post_scan()
        self.assertEqual(resp.status_code, 202)
        self.assertFalse(resp.json()['created'])
        self.assertEqual(QuoteEmailScan.objects.count(), 1)
        call.assert_not_called()

    def test_post_while_running_reuses_active_scan(self):
        scan = email_scan.queue_scan(self.email, QuoteEmailScan.TRIGGER_MANUAL, self.user)
        QuoteEmailScan.objects.filter(pk=scan.pk).update(
            status=QuoteEmailScan.STATUS_RUNNING, started_at=scan.created_at,
        )
        with patch(CALL) as call:
            resp = self.post_scan()
        call.assert_not_called()
        self.assertEqual(resp.status_code, 202)
        self.assertFalse(resp.json()['created'])
        self.assertEqual(QuoteEmailScan.objects.get().pk, scan.pk)

    def test_blocked_sender_returns_409(self):
        blocklist.add_block('email', 'sam@echelon.example')
        with patch(CALL) as call:
            resp = self.post_scan()
        call.assert_not_called()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json(), {'ok': False, 'error': BLOCKED})

    def test_worker_disabled_post_503_get_404(self):
        ScheduledTask.objects.filter(name='process_quote_email_pipeline').update(is_enabled=False)
        self.assertEqual(self.client.get(reverse('quote:email_scan', args=[self.email.pk])).status_code, 404)
        resp = self.post_scan()
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['error'], "Background scanning isn't running right now.")
        ScheduledTask.objects.filter(name='process_quote_email_pipeline').update(is_enabled=True)

    def test_settings_switch_off_does_not_block_manual_scan(self):
        app_settings.save_section('email_scan', {}, self.user)
        with patch(CALL) as call:
            resp = self.post_scan()
        call.assert_not_called()
        self.assertEqual(resp.status_code, 202)
        app_settings.save_section('email_scan', {'email_scan_enabled': 'on', 'confirm_scan_on': '1'}, self.user)

    def test_get_state_has_no_next_level(self):
        data = self.client.get(reverse('quote:email_scan', args=[self.email.pk])).json()
        self.assertNotIn('next_level', data)

    def test_login_required(self):
        client = self.client_class()
        for url in (
            reverse('quote:email_scan', args=[self.email.pk]),
            reverse('quote:email_block', args=[self.email.pk]),
            reverse('quote:email_release', args=[self.email.pk]),
        ):
            self.assertEqual(client.get(url).status_code, 302)
            self.assertEqual(client.post(url).status_code, 302)


class ExecuteBlockTests(PipelineBase):
    def test_blocked_after_queue_fails_without_claude(self):
        scan = email_scan.queue_scan(self.make_email(), QuoteEmailScan.TRIGGER_MANUAL, self.user)
        blocklist.add_block('domain', 'echelon.example')
        QuoteEmailTriage.objects.create(email=scan.email, state='extract_queued')
        with patch(CALL) as call:
            QuoteEmailScan.objects.filter(pk=scan.pk).update(status='running', started_at=scan.created_at)
            row = QuoteEmailScan.objects.select_related('email', 'email__supplier').get(pk=scan.pk)
            scan = email_scan.execute_scan(row)
        call.assert_not_called()
        self.assertEqual((scan.status, scan.error_text), ('failed', 'Sender is blocked.'))
        triage = QuoteEmailTriage.objects.get(email=scan.email)
        self.assertEqual((triage.state, triage.reason), ('blocked', 'code_block:domain'))


class BlockEndpointTests(ScanBase):
    def block_url(self, email=None):
        return reverse('quote:email_block', args=[(email or self.email).pk])

    def post_block(self, **fields):
        return self.client.post(self.block_url(), data=fields)

    def test_email_block_uses_sender_address(self):
        resp = self.post_block(block_type='email', reason='spam', value='evil@elsewhere.com')
        self.assertEqual(resp.status_code, 200)
        block = QuoteSenderBlock.objects.get()
        self.assertEqual(block.value, 'sam@echelon.example')
        triage = QuoteEmailTriage.objects.get(email=self.email)
        self.assertEqual((triage.state, triage.reason), ('blocked', 'code_block:email'))

    def test_domain_block(self):
        resp = self.post_block(block_type='domain', reason='bad actor')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(QuoteSenderBlock.objects.get().value, 'echelon.example')

    def test_supplier_block(self):
        resp = self.post_block(block_type='supplier', reason='policy')
        self.assertEqual(QuoteSenderBlock.objects.get().value, str(self.supplier.pk))

    def test_no_supplier_rejects_supplier_type(self):
        from quote.models import QuoteEmail

        email = QuoteEmail.objects.create(
            graph_message_id='AAMk-ns', sender_email='x@alone.example', received_at=self.email.received_at,
        )
        resp = self.client.post(reverse('quote:email_block', args=[email.pk]),
                                data={'block_type': 'supplier', 'reason': 'nope'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'This message has no supplier.')

    def test_empty_reason_is_400(self):
        self.assertEqual(self.post_block(block_type='email', reason='  ').status_code, 400)

    def test_public_domain_is_400(self):
        email = self.message('AAMk-gmail')
        email.sender_email = 'pat@gmail.com'
        email.save(update_fields=['sender_email'])
        resp = self.client.post(reverse('quote:email_block', args=[email.pk]),
                                data={'block_type': 'domain', 'reason': 'nope'})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(QuoteSenderBlock.objects.filter(value='gmail.com').exists())

    def test_creates_triage_when_missing(self):
        self.assertFalse(QuoteEmailTriage.objects.filter(email=self.email).exists())
        self.post_block(block_type='email', reason='new row')
        self.assertEqual(QuoteEmailTriage.objects.get(email=self.email).state, 'blocked')


class UnblockScanTests(ScanBase):
    def test_unblock_then_scan_queues(self):
        block = blocklist.add_block('email', 'sam@echelon.example')
        QuoteEmailTriage.objects.create(email=self.email, state='blocked', block_entry=block)
        blocklist.deactivate_block(block)
        with patch(CALL) as call:
            resp = self.client.post(reverse('quote:email_scan', args=[self.email.pk]))
        call.assert_not_called()
        self.assertEqual(resp.status_code, 202)
        triage = QuoteEmailTriage.objects.get(email=self.email)
        self.assertEqual((triage.state, triage.reason), ('extract_queued', 'unblocked'))


class ReleaseEndpointTests(ScanBase):
    def test_release_hold_possible_block(self):
        QuoteEmailTriage.objects.create(
            email=self.email, state=QuoteEmailTriage.STATE_HELD_POSSIBLE_BLOCK, reason='jev_block_hold',
        )
        with patch(CALL) as call:
            resp = self.client.post(reverse('quote:email_release', args=[self.email.pk]))
        call.assert_not_called()
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(QuoteEmailScan.objects.filter(trigger='manual', status='queued').exists())

    def test_release_blocked_is_409(self):
        QuoteEmailTriage.objects.create(email=self.email, state='blocked')
        resp = self.client.post(reverse('quote:email_release', args=[self.email.pk]))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], BLOCKED)


class InboxPageTests(ScanBase):
    def test_inbox_triage_badges_and_filters(self):
        states = (
            ('extracted', 'Quote ready'),
            ('extract_queued', 'Scanning'),
            ('held_unknown_sender', 'Quote · set supplier'),
            ('held_possible_block', 'Possible blocked'),
            ('blocked', 'Blocked'),
            ('failed', 'Scan failed'),
        )
        for idx, (state, badge) in enumerate(states, start=2):
            email = self.message(f'AAMk-{idx}')
            QuoteEmailTriage.objects.create(email=email, state=state)
            with self.subTest(state=state):
                html = self.client.get(reverse('quote:mailbox')).content.decode()
                self.assertIn(f'data-triage="{state}"', html)
                self.assertIn(badge, html)
        page = self.client.get(reverse('quote:mailbox')).content.decode()
        self.assertIn('data-filter="ready"', page)
        self.assertIn('data-filter="held"', page)

    def test_inbox_adds_one_triage_query(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def triage_sql_count(captured):
            return sum(1 for q in captured if 'quote_email_triage' in q['sql'].lower())

        QuoteEmailTriage.objects.create(email=self.email, state='extracted')
        extras = []
        for idx in range(2, 6):
            extra = self.message(f'AAMk-scale-{idx}')
            QuoteEmailTriage.objects.create(email=extra, state='extracted')
            extras.append(extra)

        self.client.get(reverse('quote:mailbox'))

        with CaptureQueriesContext(connection) as five_emails:
            self.client.get(reverse('quote:mailbox'))
        self.assertEqual(triage_sql_count(five_emails.captured_queries), 1)

        QuoteEmail.objects.filter(pk__in=[e.pk for e in extras]).delete()
        with CaptureQueriesContext(connection) as one_email:
            self.client.get(reverse('quote:mailbox'))
        self.assertEqual(triage_sql_count(one_email.captured_queries), 1)
        self.assertEqual(len(five_emails.captured_queries), len(one_email.captured_queries))


class DetailFragmentTests(ScanBase):
    def fragment(self, email=None):
        return self.client.get(
            reverse('quote:email_detail', args=[(email or self.email).pk]), **XHR,
        ).content.decode()

    def test_triage_panel_copy_by_state(self):
        cases = (
            ('extracted', 'Quote data extracted. Open Log supplier quote to use it.'),
            ('extract_queued', 'Scanning in the background'),
            ('held_unknown_sender', 'known supplier. Set the supplier'),
            ('held_possible_block', 'may involve a blocked company: Acme Corp'),
            ('blocked', 'Sender is blocked. This message is not sent for scanning.'),
            ('not_quote', 'Jev: probably not a quote.'),
            ('failed', 'The automatic scan failed. Click Scan quote to try again.'),
        )
        for state, snippet in cases:
            QuoteEmailTriage.objects.filter(email=self.email).delete()
            defaults = {'state': state}
            if state == 'held_possible_block':
                defaults['jev_block_label'] = 'Acme Corp'
            QuoteEmailTriage.objects.create(email=self.email, **defaults)
            with self.subTest(state=state):
                self.assertIn(snippet, self.fragment())

    def test_pending_triage_renders_no_status_alert(self):
        QuoteEmailTriage.objects.create(email=self.email, state='pending')
        html = self.fragment()
        self.assertNotIn('Scanning in the background', html)
        self.assertNotIn('Quote data extracted', html)
        self.assertNotIn('probably not a quote', html)

    def test_block_sender_menu_and_urls(self):
        html = self.fragment()
        self.assertIn('data-action="block-sender"', html)
        self.assertIn(reverse('quote:email_block', args=[self.email.pk]), html)
        self.assertIn('data-release-url', html)

    def test_gmail_sender_disables_public_domain_block(self):
        email = self.message('AAMk-gmail')
        email.sender_email = 'pat@gmail.com'
        email.save(update_fields=['sender_email'])
        html = self.fragment(email)
        self.assertIn('data-public-domain="1"', html)

    def test_no_template_leaks_in_fragment(self):
        html = self.fragment()
        for leak in ('{#', '{%'):
            self.assertNotIn(leak, html)