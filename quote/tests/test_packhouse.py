"""Packhouse quote requests: parsing, the message, preview / send / record, the reply hook, views."""
import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from dibbs.models import ImportBatch, SolAnalysis, SolPackaging, Solicitation, SolicitationLine
from products.models import Nsn
from quote.models import QuotePackhouseRFQ, QuoteSupplierQuote
from quote.services import mailbox, packhouse
from quote.services.matching import seed_solicitation_states
from suppliers.models import Contact, Supplier

SEND = 'quote.services.packhouse.send_mail_via_graph'
DIMS = {'weight': '2.5', 'length': '6', 'width': '4', 'height': '3', 'source_notes': 'spec sheet'}


class ParseDimsTests(SimpleTestCase):
    def test_blank_and_zero_mean_unknown(self):
        out = packhouse.parse_dims({'weight': '', 'length': '0', 'width': None})
        self.assertEqual(out, {'weight': None, 'length': None, 'width': None, 'height': None})

    def test_values_are_decimal_at_the_field_precision(self):
        out = packhouse.parse_dims({'weight': '2.5', 'length': '6.125', 'width': '4', 'height': '3'})
        self.assertEqual(out['weight'], Decimal('2.500'))
        self.assertEqual(out['length'], Decimal('6.13'))   # 2 dp, half up
        self.assertTrue(all(isinstance(v, Decimal) for v in out.values()))

    def test_rejects_garbage_negative_and_oversize(self):
        for bad in ('abc', '-1', '1e400', '99999999'):
            with self.assertRaises(packhouse.PackhouseError, msg=bad):
                packhouse.parse_dims({'length': bad})
        with self.assertRaises(packhouse.PackhouseError):
            packhouse.parse_dims({'weight': '10000000'})   # 10 digits, 3 dp -> max 9,999,999.999

    def test_describe(self):
        out = packhouse.describe_dims(packhouse.parse_dims(DIMS))
        self.assertEqual(out, ['Weight: 2.5 lb', 'Size (L x W x H): 6 x 4 x 3 in'])
        self.assertEqual(packhouse.describe_dims(packhouse.parse_dims({'length': '10'})), ['Length: 10 in'])
        self.assertEqual(packhouse.describe_dims(packhouse.parse_dims({})), [])


class PackhouseBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('rep', 'rep@example.com', 'x', first_name='Dion', last_name='H')
        self.client.force_login(self.user)
        today = timezone.now().date()
        batch = ImportBatch.objects.create(import_date=today, imported_at=timezone.now())
        self.sol = Solicitation.objects.create(
            solicitation_number='SPE1C126Q0528', return_by_date=today + timedelta(days=20),
            import_batch=batch, pdf_file_name='SPE1C126Q0528.PDF',
        )
        self.line1 = SolicitationLine.objects.create(
            solicitation=self.sol, nsn='8465-01-613-1241', fsc='8465', quantity=2,
            unit_of_issue='EA', line_number='0001', nomenclature='CARABINER',
        )
        self.line2 = SolicitationLine.objects.create(
            solicitation=self.sol, nsn='8465-01-613-1241', fsc='8465', quantity=3,
            unit_of_issue='EA', line_number='0002', nomenclature='CARABINER',
        )
        seed_solicitation_states([self.sol.pk])
        self.acme = Supplier.objects.create(
            name='Acme Packaging', cage_code='1PK01', is_packhouse=True, rfq_email='quotes@acmepack.com',
        )
        self.bolt = Supplier.objects.create(name='Bolt Pack', cage_code='2PK02', is_packhouse=True,
                                            primary_email='hello@boltpack.com')
        self.nomail = Supplier.objects.create(name='Ghost Pack', cage_code='3PK03', is_packhouse=True)

    def send(self, ids=None, **kw):
        kw.setdefault('dims', DIMS)
        return packhouse.send_requests(self.sol, ids or [self.acme.pk], user=self.user, **kw)


class RequirementsTests(PackhouseBase):
    def test_analysis_wins(self):
        SolAnalysis.objects.create(
            solicitation=self.sol, model_key='t', packaging_standard='MIL-STD-2073-1',
            preservation_method='Method 40', special_packaging_instructions='  Level A  ',
        )
        SolPackaging.objects.create(solicitation_number=self.sol.solicitation_number,
                                    packaging_standard='IGNORED')
        self.assertEqual(packhouse.packaging_requirements(self.sol), [
            ('Packaging standard', 'MIL-STD-2073-1'),
            ('Preservation', 'Method 40'),
            ('Special instructions', 'Level A'),
        ])

    def test_falls_back_to_section_d_then_nothing(self):
        self.assertEqual(packhouse.packaging_requirements(self.sol), [])
        SolPackaging.objects.create(solicitation_number=self.sol.solicitation_number,
                                    packaging_standard='ASTM D3951', marking_requirements='MIL-STD-129')
        self.assertEqual(packhouse.packaging_requirements(self.sol), [
            ('Packaging standard', 'ASTM D3951'), ('Marking', 'MIL-STD-129'),
        ])


class ComposeTests(PackhouseBase):
    def compose(self, dims, reqs=(), note=''):
        return packhouse.compose_message(
            self.acme, self.sol, [self.line1, self.line2], 5, packhouse.parse_dims(dims),
            list(reqs), note, self.user,
        )

    def test_sol_is_in_subject_and_body_so_replies_link(self):
        subject, body = self.compose(DIMS)
        self.assertIn('SPE1C126Q0528', subject)
        self.assertEqual(mailbox.find_sol_numbers(subject), ['SPE1C126Q0528'])
        self.assertIn('Hello Acme Packaging,', body)
        self.assertIn('Line 0001: NSN 8465-01-613-1241  CARABINER', body)
        self.assertIn('Total quantity to pack: 5 EA', body)
        self.assertIn('Weight: 2.5 lb', body)
        self.assertIn('Size (L x W x H): 6 x 4 x 3 in', body)
        self.assertIn(self.sol.dibbs_pdf_url, body)
        self.assertTrue(body.rstrip().endswith('Dion H\nSTATZ Corporation'))

    def test_unknown_dims_say_so_and_note_and_requirements_ride_along(self):
        _, body = self.compose({}, reqs=[('Packaging standard', 'MIL-STD-2073-1')], note='Need it by Friday')
        self.assertIn('not on file yet', body)
        self.assertNotIn('Weight:', body)
        self.assertIn('Packaging standard: MIL-STD-2073-1', body)
        self.assertIn('Need it by Friday', body)


class PreviewTests(PackhouseBase):
    @patch(SEND)
    def test_preview_never_sends_or_writes(self, send):
        out = packhouse.preview_request(self.sol, [self.acme.pk, self.nomail.pk], {}, user=self.user)
        send.assert_not_called()
        self.assertFalse(QuotePackhouseRFQ.objects.exists())
        by_name = {p['name']: p for p in out['packhouses']}
        self.assertEqual(by_name['Acme Packaging']['recipients'], ['quotes@acmepack.com'])
        self.assertEqual(by_name['Acme Packaging']['problem'], '')
        self.assertEqual(by_name['Ghost Pack']['problem'], 'No email address on file.')
        self.assertTrue(any('No weight or dimensions' in w for w in out['warnings']))
        self.assertTrue(any('No packaging requirements' in w for w in out['warnings']))

    @patch(SEND, return_value=True)
    def test_preview_flags_a_packhouse_we_are_still_waiting_on(self, _send):
        self.send()
        out = packhouse.preview_request(self.sol, [self.acme.pk], DIMS, user=self.user)
        self.assertIn('still waiting', out['packhouses'][0]['problem'])

    def test_mixed_nsns_with_one_set_of_dims_is_warned(self):
        self.line2.nsn = '5305-00-111-2222'
        self.line2.save()
        out = packhouse.preview_request(self.sol, [self.acme.pk], DIMS, user=self.user)
        self.assertTrue(any('more than one NSN' in w for w in out['warnings']))

    def test_input_errors(self):
        for ids in ([], [999999]):
            with self.assertRaises(packhouse.PackhouseError):
                packhouse.preview_request(self.sol, ids, {}, user=self.user)
        with self.assertRaises(packhouse.PackhouseError):
            packhouse.preview_request(self.sol, [self.acme.pk], {}, line_id=424242, user=self.user)
        many = [Supplier.objects.create(name=f'P{i}').pk for i in range(packhouse.MAX_PACKHOUSES + 1)]
        with self.assertRaises(packhouse.PackhouseError):
            packhouse.preview_request(self.sol, many, {}, user=self.user)


class SendTests(PackhouseBase):
    @patch(SEND, return_value=True)
    def test_combined_send_records_a_snapshot_per_packhouse(self, send):
        out = self.send([self.acme.pk, self.bolt.pk], note='By Friday please')
        self.assertEqual(out['sent'], 2)
        self.assertEqual(send.call_count, 2)
        first = send.call_args_list[0].kwargs
        self.assertEqual(first['to_address'], 'quotes@acmepack.com')
        self.assertIn('SPE1C126Q0528', first['subject'])
        self.assertIn('By Friday please', first['body'])

        row = QuotePackhouseRFQ.objects.get(packhouse=self.acme)
        self.assertIsNone(row.line)                      # every line on the SOL
        self.assertEqual(row.quantity, 5)                # 2 + 3
        self.assertEqual((row.weight, row.length, row.width, row.height),
                         (Decimal('2.500'), Decimal('6.00'), Decimal('4.00'), Decimal('3.00')))
        self.assertEqual(row.status, QuotePackhouseRFQ.STATUS_SENT)
        self.assertEqual(row.email_sent_to, 'quotes@acmepack.com')
        self.assertEqual(row.sent_by, self.user)
        self.assertEqual(row.note, 'By Friday please')

    @patch(SEND, return_value=True)
    def test_split_scope_prices_one_line(self, _send):
        self.send(line_id=self.line1.pk)
        row = QuotePackhouseRFQ.objects.get()
        self.assertEqual((row.line, row.quantity), (self.line1, 2))

    @patch(SEND, return_value=True)
    def test_a_solicitation_pdf_is_attached(self, send):
        Solicitation.objects.filter(pk=self.sol.pk).update(pdf_blob=b'%PDF-1.4 x')
        self.sol.refresh_from_db()
        self.send()
        self.assertEqual([a['name'] for a in send.call_args.kwargs['attachments']], ['SPE1C126Q0528.PDF'])

    @patch(SEND, return_value=False)
    def test_a_failed_send_records_nothing(self, send):
        out = self.send()
        self.assertEqual(out['sent'], 0)
        self.assertFalse(out['results'][0]['ok'])
        self.assertIn('did not send', out['results'][0]['error'])
        self.assertFalse(QuotePackhouseRFQ.objects.exists())

    @patch(SEND, return_value=True)
    def test_no_address_and_repeat_asks_are_skipped_not_sent(self, send):
        out = self.send([self.nomail.pk, self.acme.pk])
        self.assertEqual([r['ok'] for r in out['results']], [False, True])
        again = self.send([self.acme.pk])
        self.assertEqual(again['sent'], 0)
        self.assertIn('still waiting', again['results'][0]['error'])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(QuotePackhouseRFQ.objects.count(), 1)

    @patch(SEND, return_value=True)
    def test_a_different_scope_is_a_new_request(self, _send):
        self.send()
        self.assertEqual(self.send(line_id=self.line1.pk)['sent'], 1)
        self.assertEqual(QuotePackhouseRFQ.objects.count(), 2)

    @patch(SEND, return_value=True)
    def test_dimensions_only_reach_the_nsn_when_asked_and_sent(self, _send):
        nsn = Nsn.objects.create(nsn_code='8465-01-613-1241')
        self.send()
        nsn.refresh_from_db()
        self.assertIsNone(nsn.unit_weight)
        self.send([self.bolt.pk], save_dims=True)
        nsn.refresh_from_db()
        self.assertEqual(nsn.unit_weight, Decimal('2.500'))
        self.assertEqual(nsn.dimension_source_notes, 'spec sheet')

    @patch(SEND, return_value=False)
    def test_dimensions_are_not_saved_when_nothing_went_out(self, _send):
        nsn = Nsn.objects.create(nsn_code='8465-01-613-1241')
        self.send(save_dims=True)
        nsn.refresh_from_db()
        self.assertIsNone(nsn.unit_weight)


class RecordReplyTests(PackhouseBase):
    def setUp(self):
        super().setUp()
        with patch(SEND, return_value=True):
            self.send()
        self.rfq = QuotePackhouseRFQ.objects.get()    # quantity 5

    def test_total_derives_the_unit_price(self):
        packhouse.record_reply(self.rfq, self.user, total='12.50', lead_days='10', notes=' MOQ 50 ')
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.quoted_unit, Decimal('2.50000'))
        self.assertEqual(self.rfq.quoted_total, Decimal('12.50'))
        self.assertEqual((self.rfq.quoted_lead_days, self.rfq.response_notes), (10, 'MOQ 50'))
        self.assertEqual(self.rfq.status, QuotePackhouseRFQ.STATUS_RESPONDED)
        self.assertEqual(self.rfq.quoted_by, self.user)
        self.assertTrue(self.rfq.has_price)

    def test_unit_derives_the_total_and_rounds_half_up(self):
        packhouse.record_reply(self.rfq, self.user, unit='0.333335')
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.quoted_unit, Decimal('0.33334'))
        self.assertEqual(self.rfq.quoted_total, Decimal('1.67'))     # 0.33334 x 5

    def test_can_be_corrected_later(self):
        packhouse.record_reply(self.rfq, self.user, unit='1')
        packhouse.record_reply(self.rfq, self.user, unit='2')
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.quoted_unit, Decimal('2.00000'))

    def test_links_the_reply_email_when_given(self):
        email, _ = mailbox.ingest_message({
            'id': 'r1', 'subject': 'RE: Packaging RFQ SPE1C126Q0528',
            'from': {'emailAddress': {'address': 'quotes@acmepack.com', 'name': 'Sam'}},
            'receivedDateTime': (timezone.now() + timedelta(hours=1)).isoformat(),
            'bodyPreview': '$12.50', 'body': {'contentType': 'text', 'content': '$12.50'},
            'isRead': False, 'hasAttachments': False,
        })
        packhouse.record_reply(self.rfq, self.user, total='12.50', email=email)
        self.rfq.refresh_from_db()
        self.assertEqual(self.rfq.response_email, email)
        self.assertEqual(self.rfq.response_received_at, email.received_at)

    def test_bad_input_changes_nothing(self):
        for kwargs in ({}, {'total': 'abc'}, {'unit': '-1'}, {'unit': '1', 'lead_days': '0'},
                       {'unit': '1', 'lead_days': 'x'}, {'unit': '1000000000'},
                       {'total': '1e12'},        # fits the total column, but /5 overflows the unit column
                       {'total': '1e13'}):
            with self.assertRaises(packhouse.PackhouseError, msg=str(kwargs)):
                packhouse.record_reply(self.rfq, self.user, **kwargs)
        self.rfq.refresh_from_db()
        self.assertFalse(self.rfq.has_price)
        self.assertEqual(self.rfq.status, QuotePackhouseRFQ.STATUS_SENT)

    def test_a_total_needs_a_quantity_to_spread_over(self):
        QuotePackhouseRFQ.objects.filter(pk=self.rfq.pk).update(quantity=0)
        self.rfq.refresh_from_db()
        with self.assertRaises(packhouse.PackhouseError):
            packhouse.record_reply(self.rfq, self.user, total='10')


class ReplyHookTests(PackhouseBase):
    """A packhouse answering in the mailbox flips its request to Replied."""

    def setUp(self):
        super().setUp()
        Contact.objects.create(name='Sam', email='sam@acmepack.com', supplier=self.acme)
        with patch(SEND, return_value=True):
            self.send([self.acme.pk, self.bolt.pk])

    def payload(self, received, sender='sam@acmepack.com', mid='r1'):
        return {
            'id': mid, 'subject': 'RE: Packaging RFQ SPE1C126Q0528 - STATZ Corporation',
            'from': {'emailAddress': {'address': sender, 'name': 'Sam'}},
            'receivedDateTime': received.isoformat(), 'bodyPreview': 'Total $12.50',
            'body': {'contentType': 'text', 'content': 'Total $12.50'},
            'isRead': False, 'hasAttachments': False,
        }

    def test_reply_from_that_packhouse_flips_only_its_request(self):
        email, _ = mailbox.ingest_message(self.payload(timezone.now() + timedelta(hours=1)))
        self.assertEqual(email.supplier, self.acme)
        acme = QuotePackhouseRFQ.objects.get(packhouse=self.acme)
        bolt = QuotePackhouseRFQ.objects.get(packhouse=self.bolt)
        self.assertEqual(acme.status, QuotePackhouseRFQ.STATUS_RESPONDED)
        self.assertEqual(acme.response_email, email)
        self.assertEqual(bolt.status, QuotePackhouseRFQ.STATUS_SENT)
        self.assertFalse(acme.has_price)      # a reply is not a price until the rep records it

    def test_an_older_thread_cannot_answer_a_newer_request(self):
        mailbox.ingest_message(self.payload(timezone.now() - timedelta(days=2)))
        self.assertEqual(QuotePackhouseRFQ.objects.get(packhouse=self.acme).status,
                         QuotePackhouseRFQ.STATUS_SENT)


class ScreenDataTests(PackhouseBase):
    def test_history_lists_packhouses_used_on_the_nsn_newest_first(self):
        for supplier, vendor in ((self.bolt, self.bolt), (self.bolt, self.bolt), (self.bolt, self.acme)):
            QuoteSupplierQuote.objects.create(
                line=self.line1, supplier=supplier, nsn='8465016131241', supplier_unit_cost=Decimal('1'),
                lead_time_days=5, packaging_source='THIRD_PARTY', packaging_vendor=vendor,
            )
        self.assertEqual([h['name'] for h in packhouse.history({'8465016131241'})],
                         ['Acme Packaging', 'Bolt Pack'])
        self.assertEqual(packhouse.history({'0000000000000'}), [])
        self.assertEqual(packhouse.history(set()), [])

    @patch(SEND, return_value=True)
    def test_requests_payload_shape(self, _send):
        self.send()
        rows = packhouse.requests_payload([self.sol.pk])[self.sol.pk]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Acme Packaging')
        self.assertEqual((rows[0]['status'], rows[0]['scope'], rows[0]['unit']), ('SENT', 'all lines', ''))


class PackhouseViewTests(PackhouseBase):
    def post(self, name, *args, **data):
        return self.client.post(reverse(name, args=args), data,
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def fields(self, ids=None, **extra):
        data = {'packhouse_ids': ids or [self.acme.pk], 'note': 'hi',
                **{f'dim_{k}': v for k, v in DIMS.items()}}
        data.update(extra)
        return data

    @patch(SEND)
    def test_preview_endpoint(self, send):
        resp = self.post('quote:packhouse_preview', self.sol.solicitation_number, **self.fields())
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertIn('SPE1C126Q0528', body['subject'])
        self.assertEqual(body['packhouses'][0]['recipients'], ['quotes@acmepack.com'])
        send.assert_not_called()

    @patch(SEND, return_value=True)
    def test_send_endpoint_returns_the_refreshed_list(self, send):
        resp = self.post('quote:packhouse_send', self.sol.solicitation_number,
                         **self.fields([self.acme.pk, self.nomail.pk]))
        body = resp.json()
        self.assertTrue(body['ok'] and body['partial'])
        self.assertIn('Acme Packaging', body['message'])
        self.assertIn('Ghost Pack: No email address on file.', body['message'])
        self.assertEqual([r['name'] for r in body['requests']], ['Acme Packaging'])
        self.assertEqual(send.call_count, 1)

    @patch(SEND, return_value=False)
    def test_nothing_sent_is_not_ok(self, _send):
        body = self.post('quote:packhouse_send', self.sol.solicitation_number, **self.fields()).json()
        self.assertFalse(body['ok'])
        self.assertEqual(body['message'].split('.')[0], 'Nothing was sent')

    def test_bad_input_is_a_400_and_unknown_sol_a_404(self):
        for data in ({'packhouse_ids': []}, self.fields(dim_weight='abc'), self.fields(ids=['x'])):
            resp = self.post('quote:packhouse_preview', self.sol.solicitation_number, **data)
            self.assertEqual(resp.status_code, 400, data)
            self.assertFalse(resp.json()['ok'])
        self.assertEqual(self.post('quote:packhouse_preview', 'NOPE', **self.fields()).status_code, 404)

    def test_get_is_refused_and_login_is_required(self):
        url = reverse('quote:packhouse_send', args=[self.sol.solicitation_number])
        self.assertEqual(self.client.get(url).status_code, 405)
        anonymous = Client()
        self.assertNotEqual(anonymous.post(url, self.fields()).status_code, 200)
        self.assertFalse(QuotePackhouseRFQ.objects.exists())

    @patch(SEND, return_value=True)
    def test_record_reply_endpoint(self, _send):
        self.send()
        rfq = QuotePackhouseRFQ.objects.get()
        resp = self.post('quote:packhouse_record_reply', rfq.pk, total='12.50', lead_days='7')
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertEqual((body['request']['unit'], body['request']['total']), ('2.50000', '12.50'))
        self.assertIn('$2.5 per unit', body['message'])
        bad = self.post('quote:packhouse_record_reply', rfq.pk, total='')
        self.assertEqual(bad.status_code, 400)

    @patch(SEND, return_value=True)
    def test_message_pane_shows_the_banner_and_drawer_data(self, _send):
        Contact.objects.create(name='Sam', email='sam@acmepack.com', supplier=self.acme)
        self.send()
        reply, _ = mailbox.ingest_message({
            'id': 'r9', 'subject': 'RE: Packaging RFQ SPE1C126Q0528',
            'from': {'emailAddress': {'address': 'sam@acmepack.com', 'name': 'Sam'}},
            'receivedDateTime': (timezone.now() + timedelta(hours=1)).isoformat(),
            'bodyPreview': '$12.50', 'body': {'contentType': 'text', 'content': '$12.50'},
            'isRead': False, 'hasAttachments': False,
        })
        detail = self.client.get(reverse('quote:email_detail', args=[reply.pk]),
                                 HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(detail, 'Packaging quote requested from Acme Packaging')
        self.assertContains(detail, 'id="qPhReplies"')
        self.assertContains(detail, 'packhouse_requests')
        # One weight / dimensions block, shared: the fields exist once and are read out in both sections.
        content = detail.content.decode()
        self.assertEqual(content.count('name="dim_weight"'), 1)
        self.assertEqual(content.count('data-dims-readout'), 4)   # summary + packaging x2 + freight

        # Their reply is not a supplier quote waiting to be logged.
        inbox = self.client.get(reverse('quote:mailbox')).content.decode()
        quoted = re.search(r'data-id="%d".*?data-quoted="(\d+)"' % reply.pk, inbox, re.S)
        self.assertEqual(quoted.group(1), '1')

    def test_a_normal_supplier_message_has_no_banner(self):
        supplier = Supplier.objects.create(name='Vortex', cage_code='0SKY9')
        Contact.objects.create(name='Pat', email='pat@vortex.com', supplier=supplier)
        email, _ = mailbox.ingest_message({
            'id': 'v1', 'subject': 'RE: RFQ SPE1C126Q0528',
            'from': {'emailAddress': {'address': 'pat@vortex.com', 'name': 'Pat'}},
            'receivedDateTime': timezone.now().isoformat(), 'bodyPreview': 'x',
            'body': {'contentType': 'text', 'content': 'x'}, 'isRead': False, 'hasAttachments': False,
        })
        detail = self.client.get(reverse('quote:email_detail', args=[email.pk]),
                                 HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertNotContains(detail, 'id="qPhReplies"')
