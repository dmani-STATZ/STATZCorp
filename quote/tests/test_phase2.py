"""Phase 2: cost buildup, mailbox ingest + detection, quote drawer save, views."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from dibbs.models import ImportBatch, Solicitation, SolicitationLine
from products.models import Nsn
from quote.models import (
    QuoteEmail,
    QuoteEmailAttachment,
    QuoteEmailSolLink,
    QuoteRFQ,
    QuoteSolicitation,
    QuoteSupplierQuote,
)
from quote.services import cost, mailbox
from quote.services.matching import seed_solicitation_states
from quote.services.quotes import QuoteInput, QuoteInputError, save_supplier_quote
from suppliers.models import Contact, Supplier


class CostTests(SimpleTestCase):
    def test_markup_on_cost_matches_the_tip_screen(self):
        # Mockup: (32.50 + 0.60 + 20.00 / 2) * 1.02
        r = cost.build('32.50', 2, packaging_unit='0.60', freight_total='20.00', markup_pct='2')
        self.assertEqual(r['landed_unit_cost'], Decimal('43.10000'))
        self.assertEqual(r['final_government_unit_price'], Decimal('43.96'))
        self.assertEqual(r['markup_type'], 'PCT')

    def test_target_price_back_calculates_markup(self):
        r = cost.build('100', 1, target_price='104.50')
        self.assertEqual(r['effective_markup_pct'], Decimal('4.50'))
        self.assertEqual(r['markup_type'], 'FIXED')

    def test_everything_is_decimal(self):
        r = cost.build('1.1', 3, freight_total='1')
        self.assertTrue(all(isinstance(v, Decimal) for v in r.values() if v is not None and not isinstance(v, str)))

    def test_rejects_bad_input(self):
        for kwargs in ({'supplier_unit_cost': ''}, {'supplier_unit_cost': 'abc'},
                       {'supplier_unit_cost': '-1'}, {'supplier_unit_cost': '10', 'target_price': '5'}):
            with self.assertRaises(cost.CostError):
                cost.build(quantity=1, **kwargs)
        with self.assertRaises(cost.CostError):
            cost.build('10', 0, freight_total='5')  # cannot spread a total over 0 units


class DetectionTests(SimpleTestCase):
    def test_sol_numbers(self):
        self.assertEqual(
            mailbox.find_sol_numbers('RE: RFQ SPE1C126Q0528 and spe4a6-26-t-36qg'),
            ['SPE1C126Q0528', 'SPE4A626T36QG'],
        )

    def test_nsns(self):
        self.assertEqual(
            mailbox.find_nsns('NSN 5305-12-309-7497 & 5330011738300'),
            ['5305-12-309-7497', '5330-01-173-8300'],
        )


class MailboxBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('rep', 'rep@example.com', 'x', first_name='Dion')
        self.client.force_login(self.user)
        today = timezone.now().date()
        batch = ImportBatch.objects.create(import_date=today, imported_at=timezone.now())
        self.sol = Solicitation.objects.create(
            solicitation_number='SPE1C126Q0528', return_by_date=today + timedelta(days=20),
            import_batch=batch,
        )
        self.line1 = SolicitationLine.objects.create(
            solicitation=self.sol, nsn='8465-01-613-1241', fsc='8465', quantity=2,
            unit_of_issue='EA', line_number='0001', nomenclature='CARABINER', delivery_days=45,
        )
        self.line2 = SolicitationLine.objects.create(
            solicitation=self.sol, nsn='8465-01-613-1241', fsc='8465', quantity=3,
            unit_of_issue='EA', line_number='0002', nomenclature='CARABINER',
        )
        seed_solicitation_states([self.sol.pk])
        self.supplier = Supplier.objects.create(name='Vortex Tactical', cage_code='0SKY9')
        Contact.objects.create(name='Pat', email='pat@vortextactical.com', supplier=self.supplier)

    def payload(self, **over):
        p = {
            'id': 'AAMk-1', 'subject': 'RE: RFQ SPE1C126Q0528 (Carabiners)',
            'from': {'emailAddress': {'address': 'pat@vortextactical.com', 'name': 'Pat'}},
            'receivedDateTime': '2026-09-25T14:42:00Z', 'bodyPreview': 'We can supply...',
            'body': {'contentType': 'html', 'content': '<p>Price $32.50 each</p>'},
            'isRead': False, 'hasAttachments': False,
        }
        p.update(over)
        return p


class IngestTests(MailboxBase):
    def test_sol_in_subject_links_every_line_and_resolves_supplier(self):
        email, created = mailbox.ingest_message(self.payload())
        self.assertTrue(created)
        self.assertFalse(email.is_orphan)
        self.assertEqual(email.supplier, self.supplier)
        self.assertEqual(set(email.sol_links.values_list('line_id', flat=True)), {self.line1.pk, self.line2.pk})
        self.assertFalse(mailbox.ingest_message(self.payload())[1])  # idempotent

    def test_domain_fallback_for_supplier(self):
        email, _ = mailbox.ingest_message(self.payload(**{
            'id': 'x2', 'from': {'emailAddress': {'address': 'bids@vortextactical.com'}},
        }))
        self.assertEqual(email.supplier, self.supplier)

    def test_nsn_only_links_when_we_rfqd_it(self):
        body = {'contentType': 'text', 'content': 'Price for 8465-01-613-1241 is $30'}
        orphan, _ = mailbox.ingest_message(self.payload(id='n1', subject='Pricing', body=body))
        self.assertTrue(orphan.is_orphan)

        QuoteRFQ.objects.create(line=self.line1, supplier=self.supplier, status=QuoteRFQ.STATUS_SENT)
        linked, _ = mailbox.ingest_message(self.payload(id='n2', subject='Pricing', body=body))
        self.assertFalse(linked.is_orphan)
        self.assertEqual(list(linked.sol_links.values_list('line_id', flat=True)), [self.line1.pk])
        self.assertEqual(QuoteRFQ.objects.get().status, QuoteRFQ.STATUS_RESPONDED)

    def test_plain_text_body_is_escaped(self):
        email, _ = mailbox.ingest_message(self.payload(
            id='t1', body={'contentType': 'text', 'content': '<script>x</script>'},
        ))
        self.assertIn('&lt;script&gt;', email.body_html)

    @patch('quote.services.mailbox.graph_inbox')
    def test_sync_stores_only_new_messages(self, graph):
        from quote.services.graph_inbox import GraphEmailMessage
        msg = GraphEmailMessage(
            graph_id='AAMk-1', sender_email='pat@vortextactical.com', sender_name='Pat',
            subject='s', received_at=timezone.now(), body_html='', is_read=False,
        )
        graph.fetch_inbox_messages.return_value = ([msg], None)
        graph.fetch_message_full.return_value = (self.payload(hasAttachments=True), None)
        graph.fetch_attachments.return_value = ([{
            'graph_attachment_id': 'a1', 'name': 'quote.pdf', 'content_type': 'application/pdf',
            'size': 9, 'content': b'%PDF-1.4x',
        }], None)
        self.assertEqual(mailbox.sync_mailbox()['new'], 1)
        self.assertEqual(QuoteEmailAttachment.objects.count(), 1)
        self.assertEqual(mailbox.sync_mailbox()['new'], 0)


class SaveQuoteTests(MailboxBase):
    def setUp(self):
        super().setUp()
        self.email, _ = mailbox.ingest_message(self.payload())

    def _save(self, lines=None, supplier=None, **fields):
        data = QuoteInput(supplier_unit_cost=fields.pop('cost', '32.50'),
                          lead_time_days=fields.pop('lead', '30'), **fields)
        return save_supplier_quote(
            solicitation=self.sol, supplier=supplier or self.supplier,
            lines=lines or [self.line1, self.line2], data=data, user=self.user, email=self.email,
        )

    def test_combined_prices_every_line_and_spreads_totals(self):
        result = self._save(freight_total='10', markup_pct='4')
        self.assertEqual(len(result['quotes']), 2)
        q = QuoteSupplierQuote.objects.filter(line=self.line1).get()
        self.assertEqual(q.freight_adder_unit, Decimal('2.00000'))  # 10 over qty 2+3
        self.assertEqual(q.final_government_unit_price, Decimal('35.88'))  # 34.50 * 1.04
        self.assertEqual(q.source_email, self.email)
        self.assertEqual(QuoteSolicitation.objects.get(solicitation=self.sol).status, 'QUOTING')

    def test_split_prices_one_line(self):
        self._save(lines=[self.line1])
        self.assertEqual(QuoteSupplierQuote.objects.count(), 1)

    def test_lowest_landed_is_auto_selected_unless_a_rep_chose(self):
        other = Supplier.objects.create(name='Apex', cage_code='72914')
        self._save(lines=[self.line1], cost='40')
        self._save(lines=[self.line1], supplier=other, cost='30')
        selected = QuoteSupplierQuote.objects.get(line=self.line1, is_selected_for_bid=True)
        self.assertEqual(selected.supplier, other)
        self.assertTrue(selected.selected_automatically)

        QuoteSupplierQuote.objects.filter(line=self.line1).update(is_selected_for_bid=False, selected_automatically=False)
        QuoteSupplierQuote.objects.filter(line=self.line1, supplier=self.supplier).update(is_selected_for_bid=True)
        self._save(lines=[self.line1], supplier=other, cost='10')
        self.assertEqual(
            QuoteSupplierQuote.objects.get(line=self.line1, is_selected_for_bid=True).supplier, self.supplier,
        )

    def test_dimensions_update_existing_nsn_only(self):
        nsn = Nsn.objects.create(nsn_code='8465-01-613-1241')
        self._save(save_dims=True, dims={'weight': '1.5', 'length': '4', 'source_notes': 'spec sheet'})
        nsn.refresh_from_db()
        self.assertEqual(nsn.unit_weight, Decimal('1.500'))
        self.assertEqual(nsn.dimension_source_notes, 'spec sheet')
        self.assertEqual(nsn.dimensions_last_verified, timezone.now().date())

    def test_validation(self):
        with self.assertRaises(QuoteInputError):
            self._save(lead='0')
        with self.assertRaises(QuoteInputError):
            self._save(offered_cage='ABC')
        self.assertFalse(QuoteSupplierQuote.objects.exists())


class MailboxViewTests(MailboxBase):
    def setUp(self):
        super().setUp()
        # Opening a message must never write to the real mailbox.
        patcher = patch('quote.views.mailbox.graph_inbox.mark_message_read', return_value=None)
        self.mark_read = patcher.start()
        self.addCleanup(patcher.stop)
        self.email, _ = mailbox.ingest_message(self.payload(
            body={'contentType': 'html', 'content': '<p onclick="x()">Hi</p><img src="https://track.example/p.gif">'},
        ))
        self.att = QuoteEmailAttachment.objects.create(
            email=self.email, original_name='evil.html', content_type='text/html',
            file_size=5, content=b'<b>x', downloaded_at=timezone.now(),
        )
        self.xhr = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def test_inbox_and_detail_render(self):
        self.assertEqual(self.client.get(reverse('quote:mailbox')).status_code, 200)
        resp = self.client.get(reverse('quote:email_detail', args=[self.email.pk]), **self.xhr)
        self.assertContains(resp, 'sandbox="allow-popups allow-popups-to-escape-sandbox"')
        self.assertContains(resp, 'Content-Security-Policy')
        self.assertContains(resp, 'SPE1C126Q0528')
        self.email.refresh_from_db()
        self.assertTrue(self.email.is_read)
        self.mark_read.assert_not_called()
        self.assertEqual(self.email.claimed_by, self.user)

    def test_attachment_never_served_as_html(self):
        resp = self.client.get(reverse('quote:attachment_download', args=[self.att.pk]))
        self.assertEqual(resp['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment;', resp['Content-Disposition'])
        self.assertEqual(resp['X-Content-Type-Options'], 'nosniff')

    def test_link_unlink_and_save_via_http(self):
        url = reverse('quote:email_unlink', args=[self.email.pk])
        self.client.post(url, {'sol': 'SPE1C126Q0528'}, **self.xhr)
        self.email.refresh_from_db()
        self.assertTrue(self.email.is_orphan)
        self.client.post(reverse('quote:email_link', args=[self.email.pk]), {'sol': 'SPE1C126Q0528'}, **self.xhr)
        self.assertEqual(QuoteEmailSolLink.objects.filter(email=self.email).count(), 2)

        save = reverse('quote:save_quote', args=[self.email.pk])
        bad = self.client.post(save, {'sol': 'SPE1C126Q0528', 'supplier_id': self.supplier.pk,
                                      'unit_cost': '', 'lead_time_days': '30'}, **self.xhr)
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post(save, {'sol': 'SPE1C126Q0528', 'supplier_id': self.supplier.pk,
                                     'unit_cost': '32.50', 'lead_time_days': '30',
                                     'mode': 'split', 'line_id': self.line1.pk, 'markup_pct': '6'}, **self.xhr)
        self.assertTrue(ok.json()['ok'])
        self.assertEqual(QuoteSupplierQuote.objects.get().final_government_unit_price, Decimal('34.45'))
