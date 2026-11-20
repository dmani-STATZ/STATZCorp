"""RFQ Test Mode: the outbound choke point, the RFQ and packhouse send paths, and the guard test."""
from pathlib import Path
from unittest.mock import call, patch

from django.test import SimpleTestCase
from django.urls import reverse

from quote.models import QuotePackhouseRFQ, QuoteRFQ, QuoteSetting, QuoteSolicitation, QuoteTestSend
from quote.services import app_settings, outbound, packhouse
from quote.services.rfq import compose_message, queue_rfqs, send_supplier_rfqs
from quote.tests.test_packhouse import DIMS, PackhouseBase
from quote.tests.test_phase1 import Phase1Base
from suppliers.models import Contact, SupplierContactCategory

SEND = 'quote.services.outbound.send_mail_via_graph'
TEST_ADDRESS = 'qa@statz.example'
RFQ_STATE_FIELDS = ('status', 'send_attempts', 'last_send_error', 'sent_at', 'sent_by_id', 'email_sent_to')


def turn_on(recipient=TEST_ADDRESS, user=None):
    app_settings.set_value('rfq_test_recipient', recipient, user)
    app_settings.set_value('rfq_test_mode', True, user)


def all_text(mock_call):
    return ' '.join(str(v) for v in list(mock_call.args) + list(mock_call.kwargs.values()))


class RFQBase(Phase1Base):
    def setUp(self):
        super().setUp()
        QuoteSolicitation.objects.filter(solicitation=self.sol).update(status='MATCHED')
        sales, _ = SupplierContactCategory.objects.get_or_create(name='Sales')
        for email in ('pat@vortex.example', 'o<script>@vortex.example'):
            Contact.objects.create(name='<script>alert(1)</script>', email=email, supplier=self.supplier).categories.add(sales)
        queue_rfqs(self.sol, [self.supplier], self.user)

    def rfq_state(self):
        return list(QuoteRFQ.objects.order_by('pk').values(*RFQ_STATE_FIELDS))

    def sol_status(self):
        return QuoteSolicitation.objects.get(solicitation=self.sol).status


class RFQTestModeTests(RFQBase):
    @patch(SEND, return_value=True)
    def test_on_sends_only_to_the_test_address_and_changes_no_state(self, send):
        turn_on(user=self.user)
        before, status = self.rfq_state(), self.sol_status()
        result = send_supplier_rfqs(self.supplier, self.user)

        self.assertTrue(result['ok'])
        self.assertTrue(result['test'])
        self.assertEqual(result['test_recipient'], TEST_ADDRESS)
        self.assertEqual(send.call_count, 1)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['to_address'], TEST_ADDRESS)
        self.assertEqual(kwargs['cc_addresses'], [])
        self.assertNotIn('bcc_addresses', kwargs)
        self.assertTrue(kwargs['subject'].startswith('[TEST] '))
        self.assertIn('SPE1C126Q0528', kwargs['subject'])
        self.assertIn('TEST MODE \u2014 NOT SENT TO THE SUPPLIER.', kwargs['body'])
        self.assertIn('To: pat@vortex.example; Cc: o&lt;script&gt;@vortex.example; Bcc: (none)', kwargs['body'])
        self.assertIn('SOL: SPE1C126Q0528', kwargs['body'])
        text = all_text(send.call_args)
        self.assertNotIn('<script>', text)
        body_free = text.replace(kwargs['body'], '')
        self.assertNotIn('pat@vortex.example', body_free)
        self.assertNotIn('vortex.example', str(kwargs.get('reply_to') or ''))

        self.assertEqual(self.rfq_state(), before)
        self.assertEqual(self.sol_status(), status)
        row = QuoteTestSend.objects.get()
        self.assertTrue(row.ok)
        self.assertEqual((row.kind, row.test_recipient), ('rfq', TEST_ADDRESS))
        self.assertEqual(row.intended_to, 'pat@vortex.example')
        self.assertEqual(row.intended_cc, 'o<script>@vortex.example')
        self.assertEqual(row.sol_numbers, 'SPE1C126Q0528')
        self.assertEqual(row.sent_by, self.user)

    @patch(SEND, return_value=True)
    def test_a_second_test_send_is_allowed(self, send):
        turn_on()
        send_supplier_rfqs(self.supplier, self.user)
        self.assertTrue(send_supplier_rfqs(self.supplier, self.user)['ok'])
        self.assertEqual(send.call_count, 2)
        self.assertEqual(QuoteTestSend.objects.filter(ok=True).count(), 2)
        self.assertEqual(QuoteRFQ.objects.get().status, QuoteRFQ.STATUS_QUEUED)

    def _assert_refused(self, send, result):
        send.assert_not_called()
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], outbound.TEST_RECIPIENT_ERROR)
        self.assertEqual(
            result['error'],
            'Test mode is on but the test recipient is missing or not allowed. Nothing was sent.',
        )
        row = QuoteTestSend.objects.get()
        self.assertFalse(row.ok)

    @patch(SEND, return_value=True)
    def test_blank_recipient_fails_closed(self, send):
        QuoteSetting.objects.create(key='rfq_test_mode', value='true')
        before, status = self.rfq_state(), self.sol_status()
        self._assert_refused(send, send_supplier_rfqs(self.supplier, self.user))
        self.assertEqual(self.rfq_state(), before)
        self.assertEqual(self.sol_status(), status)

    @patch(SEND, return_value=True)
    def test_malformed_recipient_fails_closed(self, send):
        QuoteSetting.objects.create(key='rfq_test_mode', value='true')
        QuoteSetting.objects.create(key='rfq_test_recipient', value='a@x.com, b@x.com')
        before = self.rfq_state()
        self._assert_refused(send, send_supplier_rfqs(self.supplier, self.user))
        self.assertEqual(self.rfq_state(), before)

    @patch(SEND, return_value=True)
    def test_recipient_later_added_to_a_supplier_fails_closed(self, send):
        turn_on()
        Contact.objects.create(name='New', email=TEST_ADDRESS.upper(), supplier=self.supplier)
        before = self.rfq_state()
        self._assert_refused(send, send_supplier_rfqs(self.supplier, self.user))
        self.assertEqual(self.rfq_state(), before)

    @patch(SEND, side_effect=RuntimeError('graph exploded'))
    def test_transport_error_is_caught_and_changes_nothing(self, send):
        turn_on()
        before, status = self.rfq_state(), self.sol_status()
        result = send_supplier_rfqs(self.supplier, self.user)
        self.assertFalse(result['ok'])
        self.assertTrue(result['test'])
        self.assertNotIn('exploded', result['error'])
        self.assertEqual(self.rfq_state(), before)
        self.assertEqual(self.sol_status(), status)
        self.assertFalse(QuoteTestSend.objects.get().ok)

    @patch(SEND, return_value=False)
    def test_transport_false_changes_nothing(self, send):
        turn_on()
        before = self.rfq_state()
        result = send_supplier_rfqs(self.supplier, self.user)
        self.assertFalse(result['ok'])
        self.assertEqual(self.rfq_state(), before)
        self.assertEqual(QuoteRFQ.objects.get().send_attempts, 0)

    @patch(SEND, return_value=True)
    def test_no_recipient_in_test_mode_records_no_failure(self, send):
        turn_on()
        Contact.objects.filter(supplier=self.supplier).delete()
        self.supplier.business_email = ''
        self.supplier.save()
        before = self.rfq_state()
        self.assertFalse(send_supplier_rfqs(self.supplier, self.user)['ok'])
        send.assert_not_called()
        self.assertEqual(self.rfq_state(), before)


class RFQTestModeOffTests(RFQBase):
    @patch(SEND, return_value=True)
    def test_off_passes_the_transport_exactly_what_it_got_before(self, send):
        rfqs = list(QuoteRFQ.objects.select_related('supplier', 'line', 'line__solicitation'))
        subject, body = compose_message(self.supplier, rfqs, self.user)
        result = send_supplier_rfqs(self.supplier, self.user)

        self.assertEqual(send.call_args_list, [call(
            to_address='pat@vortex.example',
            cc_addresses=['o<script>@vortex.example'],
            subject=subject,
            body=body,
            reply_to=None,
            attachments=None,
        )])
        self.assertTrue(result['ok'])
        self.assertNotIn('test', result)
        rfq = QuoteRFQ.objects.get()
        self.assertEqual((rfq.status, rfq.send_attempts), (QuoteRFQ.STATUS_SENT, 1))
        self.assertEqual(self.sol_status(), 'RFQ_SENT')
        self.assertFalse(QuoteTestSend.objects.exists())

    @patch(SEND, return_value=True)
    def test_recipient_alone_does_not_turn_test_mode_on(self, send):
        app_settings.set_value('rfq_test_recipient', TEST_ADDRESS, self.user)
        send_supplier_rfqs(self.supplier, self.user)
        self.assertEqual(send.call_args.kwargs['to_address'], 'pat@vortex.example')

    @patch(SEND, return_value=True)
    def test_send_view_shows_the_test_message(self, send):
        turn_on()
        resp = self.client.post(reverse('quote:rfq_send', args=[self.supplier.pk]), follow=True)
        self.assertContains(
            resp, f'TEST sent to {TEST_ADDRESS}. Nothing went to the supplier; the RFQ is still queued.',
        )


class PackhouseTestModeTests(PackhouseBase):
    @patch(SEND, return_value=True)
    def test_on_sends_to_the_test_address_and_records_nothing(self, send):
        turn_on()
        out = self.send([self.acme.pk], save_dims=True)
        self.assertEqual(send.call_count, 1)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['to_address'], TEST_ADDRESS)
        self.assertEqual(kwargs['cc_addresses'], [])
        self.assertTrue(kwargs['subject'].startswith('[TEST] Packaging RFQ SPE1C126Q0528'))
        self.assertIn('To: quotes@acmepack.com', kwargs['body'])
        self.assertNotIn('quotes@acmepack.com', all_text(send.call_args).replace(kwargs['body'], ''))
        self.assertEqual((out['sent'], out['test_sent'], out['dims_saved']), (0, 1, []))
        self.assertTrue(out['results'][0]['ok'])
        self.assertTrue(out['results'][0]['test'])
        self.assertFalse(QuotePackhouseRFQ.objects.exists())
        self.assertEqual(QuoteTestSend.objects.get().kind, 'packhouse')

    @patch(SEND, return_value=True)
    def test_a_repeat_test_send_is_not_blocked_as_a_duplicate(self, send):
        self.send()                                   # a real request is still open
        turn_on()
        again = self.send()
        self.assertTrue(again['results'][0]['ok'])
        self.assertEqual(send.call_count, 2)
        self.assertEqual(QuotePackhouseRFQ.objects.count(), 1)
        preview = packhouse.preview_request(self.sol, [self.acme.pk], DIMS, user=self.user)
        self.assertEqual(preview['packhouses'][0]['problem'], '')

    @patch(SEND, return_value=True)
    def test_fail_closed(self, send):
        QuoteSetting.objects.create(key='rfq_test_mode', value='true')
        out = self.send()
        send.assert_not_called()
        self.assertEqual(out['results'][0]['error'], outbound.TEST_RECIPIENT_ERROR)
        self.assertFalse(QuotePackhouseRFQ.objects.exists())

    def test_preview_only_adds_keys(self):
        off = packhouse.preview_request(self.sol, [self.acme.pk], DIMS, user=self.user)
        self.assertEqual(off['test_mode'], {'on': False, 'recipient': ''})
        self.assertNotIn('effective_to', off)
        turn_on()
        on = packhouse.preview_request(self.sol, [self.acme.pk], DIMS, user=self.user)
        self.assertEqual(on['test_mode'], {'on': True, 'recipient': TEST_ADDRESS})
        self.assertEqual(on['effective_to'], TEST_ADDRESS)
        for key in ('subject', 'body', 'packhouses', 'warnings', 'attachments'):
            self.assertEqual(on[key], off[key], key)

    @patch(SEND, return_value=True)
    def test_test_mode_is_read_once_and_passed_down(self, send):
        turn_on()
        with patch('quote.services.outbound.test_mode_state', wraps=outbound.test_mode_state) as read:
            self.send([self.acme.pk, self.bolt.pk])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(send.call_count, 2)
        self.assertTrue(all(c.kwargs['to_address'] == TEST_ADDRESS for c in send.call_args_list))

    @patch(SEND, return_value=True)
    def test_off_is_unchanged(self, send):
        self.send()
        kwargs = send.call_args.kwargs
        self.assertEqual(set(kwargs), {'to_address', 'cc_addresses', 'subject', 'body', 'reply_to', 'attachments'})
        self.assertEqual((kwargs['to_address'], kwargs['cc_addresses']), ('quotes@acmepack.com', None))
        self.assertFalse(kwargs['subject'].startswith('[TEST]'))
        self.assertEqual(QuotePackhouseRFQ.objects.count(), 1)


class TransportGuardTests(SimpleTestCase):
    """Only services/outbound.py may touch the mail transport."""

    def test_no_other_quote_module_references_the_transport(self):
        root = Path(__file__).resolve().parents[1]
        offenders = []
        for path in root.rglob('*.py'):
            rel = path.relative_to(root).as_posix()
            if rel.startswith('tests/') or rel == 'services/outbound.py':
                continue
            text = path.read_text(encoding='utf-8')
            if any(term in text for term in ('send_mail_via_graph', 'sendMail', 'mailer.services.graph_mail')):
                offenders.append(rel)
        self.assertEqual(offenders, [])
