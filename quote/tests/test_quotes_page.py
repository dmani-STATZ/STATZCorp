"""The Quotes page: waiting list, logged quotes, the tray without a message, close-out / remove actions."""
import re
from datetime import timedelta
from decimal import Decimal

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from quote.models import QuoteBid, QuoteRFQ, QuoteSupplierQuote
from quote.services.quotes import saved_cards
from quote.tests.test_quote_manual import ManualBase

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class QuotesPageBase(ManualBase):
    def page(self, **params):
        return self.client.get(reverse('quote:quotes'), params)

    def tray(self, **params):
        params.setdefault('sol', self.sol.solicitation_number)
        params.setdefault('supplier', self.supplier.pk)
        return self.client.get(reverse('quote:quote_tray'), params, **XHR)

    def save(self, sol=None, **fields):
        data = {'supplier_id': self.supplier.pk, 'unit_cost': '32.50', 'lead_time_days': '45', 'markup_pct': '2',
                'source_channel': 'PHONE', 'mode': 'combined'}
        data.update(fields)
        return self.client.post(reverse('quote:quote_save', args=[sol or self.sol.solicitation_number]), data, **XHR)

    def cards(self, supplier=None):
        return saved_cards(supplier or self.supplier, [self.sol]).get(self.sol.solicitation_number, [])


class PageTests(QuotesPageBase):
    def test_the_nav_has_a_quotes_link_after_the_mailbox(self):
        html = self.page().content.decode()
        self.assertRegex(html, r'>Mailbox</a>\s*<a href="%s"\s+class="app-subnav-link active">Quotes</a>' % reverse('quote:quotes'))

    def test_waiting_tab_lists_who_owes_us_a_quote_and_the_count(self):
        self.rfq(self.line1); self.rfq(self.line2); self.rfq(self.line1, supplier=self.apex)
        html = self.page().content.decode()
        self.assertContains(self.page(), 'Vortex Tactical')
        self.assertContains(self.page(), 'Apex Fasteners')
        self.assertRegex(html, r'Waiting on suppliers <span class="badge text-bg-secondary ms-1">2</span>')
        self.assertEqual(html.count('data-enter-quote'), 2)
        self.assertIn('+1 more line', html)                                # Vortex owes both lines

    def test_a_supplier_drops_off_when_their_quote_is_entered(self):
        self.rfq(self.line1); self.rfq(self.line2)
        self.assertTrue(self.save().json()['ok'])
        html = self.page().content.decode()
        self.assertNotIn('data-enter-quote', html)
        self.assertIn('Nobody is owing us a quote', html)

    def test_replied_and_closed_states(self):
        self.rfq(self.line1, status=QuoteRFQ.STATUS_RESPONDED)
        self.rfq(self.line1, supplier=self.apex, status=QuoteRFQ.STATUS_DECLINED)
        html = self.page().content.decode()
        self.assertIn('Replied &middot; not entered', html)
        self.assertNotIn('Apex Fasteners', html)
        closed = self.page(closed=1).content.decode()
        self.assertIn('Apex Fasteners', closed)
        self.assertIn('Back to waiting', closed)

    def test_logged_tab_shows_quotes_with_edit_and_remove_and_hides_sent_ones(self):
        self.save()
        self.save(supplier_id=self.apex.pk, unit_cost='31')
        html = self.page(tab='logged').content.decode()
        self.assertEqual(html.count('data-edit-quote'), 2)
        self.assertEqual(html.count('data-remove-quote'), 2)
        self.assertIn('Phone ·'.replace('·', '&middot;') if '&middot;' in html else 'Phone ·', html)
        row = QuoteSupplierQuote.objects.filter(supplier=self.supplier).first()
        self.bid(row, QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(), exported_bq_file='bq260929-101500.txt')
        pending = self.page(tab='logged').content.decode()
        self.assertEqual(pending.count('data-edit-quote'), 1)
        both = self.page(tab='logged', sent=1).content.decode()
        self.assertEqual(both.count('data-edit-quote'), 2)
        self.assertIn('Sent to DIBBS', both)
        self.assertEqual(both.count('data-remove-quote'), 1)                  # a sent quote cannot be removed

    def test_no_template_syntax_reaches_the_browser(self):
        self.rfq(self.line1); self.save(supplier_id=self.apex.pk)
        for name, html in (('waiting', self.page().content.decode()), ('logged', self.page(tab='logged').content.decode()),
                           ('tray', self.tray().content.decode())):
            self.assertNotIn('{#', html, name)
            self.assertNotIn('{%', html, name)

    def test_every_url_needs_a_login(self):
        anon = Client()
        for name, args in (('quotes', []), ('quote_tray', []), ('quote_sol_suppliers', []), ('rfq_close', []),
                           ('quote_remove', []), ('quote_save', [self.sol.solicitation_number])):
            self.assertNotEqual(anon.get(reverse(f'quote:{name}', args=args)).status_code, 200, name)
            self.assertNotEqual(anon.post(reverse(f'quote:{name}', args=args), {}).status_code, 200, name)


class NextStepTests(QuotesPageBase):
    """From a quote to the Bid Board: nothing "triggers" it, so the screens have to point the way."""

    def board(self, **params):
        return self.client.get(reverse('quote:bid_board'), params).content.decode()

    def test_a_quote_on_an_open_solicitation_shows_under_needs_bid_and_the_quotes_page_offers_build_bid(self):
        self.save()
        builder = reverse('quote:bid_builder', args=[self.sol.solicitation_number])
        html = self.page(tab='logged').content.decode()
        self.assertIn('Build bid', html)
        self.assertIn(f'href="{builder}"', html)
        self.assertIn('Press <strong>Build bid</strong>', html)
        board = self.board()
        self.assertIn(self.sol.solicitation_number, board)
        self.assertIn('Build bid', board)
        self.assertNotIn('already exported', board)

    def test_the_link_follows_the_bid_through_its_stages(self):
        self.save()
        row = QuoteSupplierQuote.objects.first()
        bid = self.bid(row, QuoteBid.STATUS_DRAFT)
        self.assertIn('Continue &rarr;', self.page(tab='logged').content.decode())
        bid.bid_status = QuoteBid.STATUS_READY
        bid.save()
        html = self.page(tab='logged').content.decode()
        self.assertIn('Bid ready', html)
        self.assertIn(f'href="{reverse("quote:bid_export")}"', html)
        self.assertNotIn('Build bid</a>', html)

    def test_an_empty_board_says_when_solicitations_are_hidden_because_they_already_went_to_dibbs(self):
        """The demo data does exactly this: every bid exported, so nothing is left to bid and the board looks empty."""
        self.save()
        row = QuoteSupplierQuote.objects.first()
        self.bid(row, QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(), exported_bq_file='bq260929-101500.txt')
        # The second line has no bid, so the solicitation still needs one: shown, no warning.
        self.assertNotIn('already exported', self.board())
        second = QuoteSupplierQuote.objects.exclude(pk=row.pk).get()
        self.bid(second, QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(), exported_bq_file='bq260929-101500.txt')
        board = self.board()
        self.assertNotIn(f'>{self.sol.solicitation_number}</a>', board)              # not listed ...
        self.assertIn('1 open solicitation with quotes is not listed here', board)   # ... and it says why
        self.assertIn('already exported to DIBBS', board)
        self.assertIn('Nothing needs a bid', board)
        self.assertIn(reverse('quote:quotes'), board)                                # and where to go next

    def test_the_ready_tab_explains_the_route(self):
        self.assertIn('Save &amp; mark ready', self.board(tab='ready'))


class TrayTests(QuotesPageBase):
    def test_the_fragment_is_the_tray_with_the_how_did_it_reach_you_fields(self):
        html = self.tray().content.decode()
        for hook in ('id="quoteDrawer"', 'id="qChannel"', 'id="qReceived"', 'id="qContact"', 'id="qFields"'):
            self.assertIn(hook, html)
        self.assertIn(f'data-save-url="{reverse("quote:quote_save", args=[self.sol.solicitation_number])}"', html)
        self.assertIn(f'data-draft-scope="manual-{self.supplier.pk}"', html)
        self.assertIn('Log quote &mdash; Vortex Tactical', html)
        self.assertRegex(html, r'<input type="date"[^>]*max="%s"' % timezone.localdate().isoformat())
        self.assertEqual(html.count('name="dim_weight"'), 1)                # still the one shared dimensions block

    def test_it_carries_the_suppliers_quotes_and_the_lines_left_to_quote(self):
        self.save(mode='split', line_id=self.line1.pk, contact_name='Sam')
        html = self.tray().content.decode()
        self.assertRegex(html, r'"cards": \[\{"entry": "[0-9a-f]{32}"')
        self.assertIn(f'"uncovered": [{self.line2.pk}]', html)
        self.assertIn('"channel": "PHONE"', html)
        self.assertIn('"contact": "Sam"', html)
        other = self.tray(supplier=self.apex.pk).content.decode()
        self.assertIn('"cards": []', other)

    def test_unknown_solicitation_or_supplier_is_a_404(self):
        self.assertEqual(self.tray(sol='NOPE').status_code, 404)
        self.assertEqual(self.tray(supplier=999999).status_code, 404)

    def test_the_mailbox_fragment_does_not_get_the_manual_fields(self):
        email_html = self.client.get(reverse('quote:email_detail', args=[self.email.pk]), **XHR).content.decode()
        self.assertNotIn('id="qChannel"', email_html)
        self.assertIn('id="quoteDrawer"', email_html)


class SaveTests(QuotesPageBase):
    def test_a_phone_quote_is_saved_with_how_when_and_who(self):
        body = self.save(contact_name='Sam at the counter', received_on=(timezone.localdate() - timedelta(days=1)).isoformat()).json()
        self.assertTrue(body['ok'], body)
        self.assertTrue(body['message'].startswith('Saved Vortex Tactical at $'), body['message'])
        rows = QuoteSupplierQuote.objects.all()
        self.assertEqual(rows.count(), 2)
        q = rows[0]
        self.assertEqual((q.source_channel, q.source_email, q.contact_name, q.received_on),
                         ('PHONE', None, 'Sam at the counter', timezone.localdate() - timedelta(days=1)))
        self.assertEqual(q.entered_by, self.user)

    def test_the_channel_is_required_and_bad_input_saves_nothing(self):
        self.assertEqual(self.save(source_channel='').status_code, 400)
        self.assertEqual(self.save(source_channel='PIGEON').status_code, 400)
        self.assertEqual(self.save(received_on='2999-01-01').status_code, 400)
        self.assertEqual(self.save(lead_time_days='0').status_code, 400)
        self.assertEqual(self.save(supplier_id='').status_code, 400)
        self.assertFalse(QuoteSupplierQuote.objects.exists())

    def test_a_revised_quote_updates_the_one_on_file_and_says_so(self):
        self.save()
        body = self.save(unit_cost='30.00', source_channel='FAX', contact_name='fax 55').json()
        self.assertTrue(body['message'].startswith('Updated Vortex Tactical'), body['message'])
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        self.assertEqual({(q.source_channel, q.supplier_unit_cost) for q in QuoteSupplierQuote.objects.all()},
                         {('FAX', Decimal('30.00000'))})

    def test_a_new_quote_can_be_limited_to_the_lines_still_open(self):
        self.save(mode='split', line_id=self.line1.pk, unit_cost='40')
        # The tray sends the open lines; a "Combined" form must not touch the line that is already quoted.
        resp = self.save(line_ids=[self.line2.pk], unit_cost='35')
        self.assertTrue(resp.json()['ok'])
        by_line = {q.line_id: q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}
        self.assertEqual(by_line, {self.line1.pk: Decimal('40.00000'), self.line2.pk: Decimal('35.00000')})
        self.assertEqual([c['covers'] for c in self.cards()], ['Line 0001', 'Line 0002'])

    def test_line_ids_from_another_solicitation_are_ignored(self):
        from dibbs.models import Solicitation, SolicitationLine
        other = Solicitation.objects.create(solicitation_number='SPE1C126Q0999', return_by_date=self.sol.return_by_date,
                                            import_batch=self.sol.import_batch)
        stray = SolicitationLine.objects.create(solicitation=other, nsn='5305-00-111-2222', quantity=1, line_number='0001')
        resp = self.save(line_ids=[stray.pk])
        self.assertEqual(resp.status_code, 400)                            # nothing on this SOL was named
        self.assertFalse(QuoteSupplierQuote.objects.exists())

    def test_editing_by_entry_and_the_lock(self):
        self.save()
        entry = self.cards()[0]['entry']
        body = self.save(entry=entry, unit_cost='33.00', contact_name='changed').json()
        self.assertTrue(body['message'].startswith('Updated'), body['message'])
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        row = QuoteSupplierQuote.objects.first()
        self.bid(row, QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(), exported_bq_file='bq260929-101500.txt')
        locked = self.save(entry=entry, unit_cost='1.00')
        self.assertEqual(locked.status_code, 409)
        self.assertTrue(locked.json()['locked'])
        self.assertEqual(self.save(entry='nope').status_code, 404)
        self.assertEqual({q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}, {Decimal('33.00000')})

    def test_editing_an_email_quote_here_keeps_its_message_link_unless_the_source_changed(self):
        self.log()                                                          # from the mailbox message
        entry = self.cards()[0]['entry']
        first = QuoteSupplierQuote.objects.first()
        self.assertEqual(first.source_email, self.email)
        self.save(entry=entry, unit_cost='31', source_channel='EMAIL',
                  received_on=first.received_on.isoformat(), contact_name='')
        self.assertEqual(QuoteSupplierQuote.objects.first().source_email, self.email)      # untouched: same source
        self.save(entry=entry, unit_cost='30', source_channel='PHONE',
                  received_on=first.received_on.isoformat(), contact_name='Sam')
        moved = QuoteSupplierQuote.objects.first()
        self.assertEqual((moved.source_channel, moved.source_email), ('PHONE', None))       # now a phone quote

    def test_a_manual_quote_answers_the_rfq(self):
        rfq = self.rfq(self.line1)
        self.save(mode='split', line_id=self.line1.pk)
        rfq.refresh_from_db()
        self.assertEqual(rfq.status, QuoteRFQ.STATUS_RESPONDED)

    def test_the_mailbox_save_takes_line_ids_too(self):
        self.client.post(reverse('quote:save_quote', args=[self.email.pk]), {
            'sol': self.sol.solicitation_number, 'supplier_id': self.supplier.pk, 'unit_cost': '32.50',
            'lead_time_days': '45', 'markup_pct': '2', 'line_ids': [self.line2.pk]}, **XHR)
        self.assertEqual([q.line_id for q in QuoteSupplierQuote.objects.all()], [self.line2.pk])


class ActionTests(QuotesPageBase):
    def close(self, **fields):
        data = {'sol': self.sol.solicitation_number, 'supplier_id': self.supplier.pk}
        data.update(fields)
        return self.client.post(reverse('quote:rfq_close'), data, **XHR)

    def test_close_out_with_a_reason_and_bring_them_back(self):
        r = self.rfq(self.line1)
        body = self.close(action='declined', reason='no longer stocks it').json()
        self.assertTrue(body['ok'])
        self.assertIn('declined', body['message'])
        r.refresh_from_db()
        self.assertEqual((r.status, r.declined_reason), (QuoteRFQ.STATUS_DECLINED, 'no longer stocks it'))
        self.assertNotIn('data-enter-quote', self.page().content.decode())
        self.assertTrue(self.close(action='reopen').json()['ok'])
        r.refresh_from_db()
        self.assertEqual(r.status, QuoteRFQ.STATUS_SENT)
        self.assertIn('data-enter-quote', self.page().content.decode())

    def test_no_response(self):
        r = self.rfq(self.line1)
        self.assertTrue(self.close(action='no_response').json()['ok'])
        r.refresh_from_db()
        self.assertEqual(r.status, QuoteRFQ.STATUS_NO_RESPONSE)

    def test_bad_requests(self):
        self.assertEqual(self.close(action='declined').status_code, 400)          # nothing is waiting
        self.rfq(self.line1)
        self.assertEqual(self.close(action='explode').status_code, 400)
        self.assertEqual(self.close(action='reopen').status_code, 400)            # nothing to reopen
        self.assertEqual(self.close(action='no_response', sol='NOPE').status_code, 404)
        self.assertEqual(self.close(action='no_response', supplier_id=999999).status_code, 404)

    def remove(self, **fields):
        data = {'sol': self.sol.solicitation_number, 'supplier_id': self.supplier.pk,
                'entry': fields.pop('entry', None) or self.cards()[0]['entry']}
        data.update(fields)
        return self.client.post(reverse('quote:quote_remove'), data, **XHR)

    def test_remove_a_quote_and_the_supplier_is_waiting_again(self):
        rfq = self.rfq(self.line1)
        self.save(mode='split', line_id=self.line1.pk)
        self.assertNotIn('data-enter-quote', self.page().content.decode())
        body = self.remove().json()
        self.assertTrue(body['ok'], body)
        self.assertFalse(QuoteSupplierQuote.objects.exists())
        rfq.refresh_from_db()
        self.assertEqual(rfq.status, QuoteRFQ.STATUS_SENT)
        self.assertIn('data-enter-quote', self.page().content.decode())

    def test_remove_refuses_when_a_bid_rests_on_it(self):
        self.save()
        row = QuoteSupplierQuote.objects.first()
        entry = row.entry
        bid = self.bid(row, QuoteBid.STATUS_DRAFT)
        resp = self.remove(entry=entry)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Bid Board', resp.json()['error'])
        bid.bid_status = QuoteBid.STATUS_SUBMITTED
        bid.submitted_at = timezone.now()
        bid.save()
        resp = self.remove(entry=entry)
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json()['locked'])
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        self.assertEqual(self.remove(entry='nope').status_code, 404)

    def test_the_enter_a_quote_picker_lists_who_we_asked(self):
        self.rfq(self.line1); self.rfq(self.line1, supplier=self.apex, status=QuoteRFQ.STATUS_NO_RESPONSE)
        self.save(supplier_id=self.apex.pk)
        data = self.client.get(reverse('quote:quote_sol_suppliers'), {'sol': self.sol.solicitation_number}).json()
        self.assertEqual(data['sol'], self.sol.solicitation_number)
        self.assertEqual({s['name']: s['state'] for s in data['suppliers']},
                         {'Vortex Tactical': 'waiting', 'Apex Fasteners': 'quoted'})
        self.assertEqual(self.client.get(reverse('quote:quote_sol_suppliers'), {'sol': 'NOPE'}).status_code, 404)
