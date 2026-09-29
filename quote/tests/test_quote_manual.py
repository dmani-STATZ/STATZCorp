"""One quote per supplier per line, quotes entered by hand, delete, and the Quotes page's queries."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from dibbs.models import Solicitation, SolicitationLine
from quote.models import (
    QuoteBid,
    QuoteEmail,
    QuoteRFQ,
    QuoteSolicitation,
    QuoteSupplierQuote,
)
from quote.services import mailbox, quote_review
from quote.services.matching import seed_solicitation_states
from quote.services.quotes import (
    QuoteInput,
    QuoteInputError,
    QuoteLockedError,
    delete_quotes,
    quotes_for_entry,
    save_supplier_quote,
    saved_cards,
    uncovered_lines,
    update_supplier_quote,
    via_text,
)
from quote.tests.test_phase2 import MailboxBase
from suppliers.models import Supplier


class ManualBase(MailboxBase):
    def setUp(self):
        super().setUp()
        self.email, _ = mailbox.ingest_message(self.payload())
        self.apex = Supplier.objects.create(name='Apex Fasteners', cage_code='72914')
        self.lines = [self.line1, self.line2]

    def data(self, **over):
        base = dict(supplier_unit_cost='32.50', lead_time_days='45', markup_pct='2')
        base.update(over)
        return QuoteInput(**base)

    def log(self, lines=None, supplier=None, email='default', **over):
        return save_supplier_quote(
            solicitation=self.sol, supplier=supplier or self.supplier, lines=lines or self.lines,
            data=self.data(**over), user=self.user, email=self.email if email == 'default' else email,
        )

    def phone(self, lines=None, supplier=None, **over):
        over.setdefault('source_channel', 'PHONE')
        return self.log(lines=lines, supplier=supplier, email=None, **over)

    def rfq(self, line, supplier=None, status=QuoteRFQ.STATUS_SENT, days_ago=3):
        return QuoteRFQ.objects.create(
            line=line, supplier=supplier or self.supplier, status=status,
            sent_at=timezone.now() - timedelta(days=days_ago),
        )

    def bid(self, quote, status, **extra):
        return QuoteBid.objects.create(
            line=quote.line, selected_quote=quote, quoter_cage='0SKY9', quote_for_cage='0SKY9',
            unit_price=quote.final_government_unit_price, delivery_days=quote.lead_time_days,
            manufacturer_dealer='DD', bid_status=status, **extra,
        )


class OneQuotePerSupplierPerLineTests(ManualBase):
    def test_quoting_a_line_again_updates_it_instead_of_adding_a_second(self):
        first = self.log()
        self.assertEqual((first['created'], first['updated']), (2, 0))
        pks = sorted(QuoteSupplierQuote.objects.values_list('pk', flat=True))
        again = self.log(supplier_unit_cost='30.00', lead_time_days='40')
        self.assertEqual((again['created'], again['updated']), (0, 2))
        self.assertEqual(sorted(QuoteSupplierQuote.objects.values_list('pk', flat=True)), pks)
        self.assertEqual({q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}, {Decimal('30.00000')})
        self.assertEqual({q.lead_time_days for q in QuoteSupplierQuote.objects.all()}, {40})
        self.assertEqual({q.modified_by for q in QuoteSupplierQuote.objects.all()}, {self.user})

    def test_a_revised_quote_by_a_later_message_or_a_phone_call_updates_the_same_rows(self):
        self.log()
        later, _ = mailbox.ingest_message(self.payload(id='later', subject='RE: RFQ SPE1C126Q0528 revised'))
        self.log(email=later, supplier_unit_cost='31')
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        self.assertEqual({q.source_email_id for q in QuoteSupplierQuote.objects.all()}, {later.pk})
        self.phone(supplier_unit_cost='29', contact_name='Sam')
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        row = QuoteSupplierQuote.objects.first()
        self.assertEqual((row.source_email, row.source_channel, row.contact_name, row.supplier_unit_cost),
                         (None, 'PHONE', 'Sam', Decimal('29.00000')))

    def test_another_supplier_keeps_its_own_quote_on_the_same_line(self):
        self.log()
        self.log(supplier=self.apex, supplier_unit_cost='31')
        self.assertEqual(QuoteSupplierQuote.objects.filter(line=self.line1).count(), 2)
        self.assertEqual(QuoteSupplierQuote.objects.filter(line=self.line1, supplier=self.apex).count(), 1)

    def test_a_save_over_a_mix_of_quoted_and_new_lines_updates_and_creates(self):
        self.log(lines=[self.line1], supplier_unit_cost='40')
        result = self.log(supplier_unit_cost='33')                       # both lines: line 1 exists, line 2 is new
        self.assertEqual((result['created'], result['updated']), (1, 1))
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        self.assertEqual(len({q.entry for q in QuoteSupplierQuote.objects.all()}), 1)      # now one quote again

    def test_a_quote_already_sent_to_dibbs_cannot_be_replaced(self):
        rows = self.log()['quotes']
        self.bid(rows[0], QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(), exported_bq_file='bq260929-101500.txt')
        with self.assertRaises(QuoteLockedError):
            self.log(supplier_unit_cost='1')
        with self.assertRaises(QuoteLockedError):
            self.phone(lines=[self.line1], supplier_unit_cost='1')
        self.assertEqual({q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}, {Decimal('32.50000')})

    def test_the_bid_being_built_follows_a_revised_quote(self):
        rows = self.log()['quotes']
        bid = self.bid(rows[0], QuoteBid.STATUS_DRAFT)
        result = self.log(supplier_unit_cost='34.00')
        bid.refresh_from_db()
        self.assertEqual(bid.unit_price, Decimal('34.68000'))
        self.assertTrue(any('now bids $34.68' in n for n in result['bid_notes']), result['bid_notes'])

    def test_uncovered_lines_are_the_ones_the_supplier_has_not_quoted(self):
        self.assertEqual(uncovered_lines(self.supplier, self.sol), [self.line1, self.line2])
        self.log(lines=[self.line1])
        self.assertEqual(uncovered_lines(self.supplier, self.sol), [self.line2])
        self.assertEqual(uncovered_lines(self.apex, self.sol), [self.line1, self.line2])

    def test_a_legacy_duplicate_is_updated_on_its_newest_row(self):
        old = self.log(lines=[self.line1])['quotes'][0]
        dup = QuoteSupplierQuote.objects.create(              # a second row from before the rule existed
            line=self.line1, supplier=self.supplier, nsn=old.nsn, supplier_unit_cost=Decimal('50'),
            lead_time_days=10, final_government_unit_price=Decimal('51'))
        self.log(lines=[self.line1], supplier_unit_cost='31')
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        self.assertEqual(QuoteSupplierQuote.objects.get(pk=dup.pk).supplier_unit_cost, Decimal('31.00000'))
        self.assertEqual(QuoteSupplierQuote.objects.get(pk=old.pk).supplier_unit_cost, Decimal('32.50000'))


class ManualEntryTests(ManualBase):
    def test_a_phone_quote_records_how_when_and_who(self):
        today = timezone.localdate()
        self.phone(source_channel='PHONE', received_on=(today - timedelta(days=1)).isoformat(), contact_name='  Sam at the counter ')
        q = QuoteSupplierQuote.objects.first()
        self.assertEqual((q.source_channel, q.received_on, q.contact_name, q.source_email),
                         ('PHONE', today - timedelta(days=1), 'Sam at the counter', None))
        self.assertEqual(via_text(q), f"Phone · {(today - timedelta(days=1)):%b %d} · Sam at the counter")

    def test_the_channel_defaults_to_other_and_the_date_to_today(self):
        self.log(email=None)
        q = QuoteSupplierQuote.objects.first()
        self.assertEqual((q.source_channel, q.received_on), ('OTHER', timezone.localdate()))

    def test_bad_channel_or_date_saves_nothing(self):
        for bad in ({'source_channel': 'CARRIER_PIGEON'}, {'received_on': 'yesterday'},
                    {'received_on': (timezone.localdate() + timedelta(days=2)).isoformat()}):
            with self.assertRaises(QuoteInputError, msg=str(bad)):
                self.phone(**bad)
        self.assertFalse(QuoteSupplierQuote.objects.exists())

    def test_email_quotes_are_dated_by_the_message(self):
        self.log()
        q = QuoteSupplierQuote.objects.first()
        self.assertEqual(q.source_channel, 'EMAIL')
        self.assertEqual(q.received_on, timezone.localtime(self.email.received_at).date())

    def test_a_manual_quote_answers_the_rfq_and_a_written_off_supplier_is_back_in_play(self):
        sent = self.rfq(self.line1)
        declined = self.rfq(self.line2, status=QuoteRFQ.STATUS_DECLINED)
        queued = self.rfq(self.line2, supplier=self.apex, status=QuoteRFQ.STATUS_QUEUED)
        self.phone()
        for rfq, want in ((sent, QuoteRFQ.STATUS_RESPONDED), (declined, QuoteRFQ.STATUS_RESPONDED),
                          (queued, QuoteRFQ.STATUS_QUEUED)):
            rfq.refresh_from_db()
            self.assertEqual(rfq.status, want)
        self.assertEqual(QuoteSupplierQuote.objects.get(line=self.line1).rfq, sent)      # the quote points at its RFQ

    def test_a_manual_quote_moves_the_solicitation_to_quoting(self):
        self.phone()
        self.assertEqual(QuoteSolicitation.objects.get(solicitation=self.sol).status, QuoteSolicitation.STATUS_QUOTING)

    def test_editing_follows_the_newest_source(self):
        rows = self.log()['quotes']
        self.update(rows, email=None, source_channel='FAX', contact_name='fax #55')      # a hand entry always wins
        q = QuoteSupplierQuote.objects.first()
        self.assertEqual((q.source_channel, q.source_email, q.contact_name), ('FAX', None, 'fax #55'))
        later, _ = mailbox.ingest_message(self.payload(id='later', subject='RE: SPE1C126Q0528'))
        self.update(QuoteSupplierQuote.objects.all(), email=later)                        # a message replaces a hand entry
        self.assertEqual(QuoteSupplierQuote.objects.first().source_email, later)
        older, _ = mailbox.ingest_message(self.payload(id='older', receivedDateTime='2026-09-01T10:00:00Z'))
        self.update(QuoteSupplierQuote.objects.all(), email=older)                        # an older one does not
        self.assertEqual(QuoteSupplierQuote.objects.first().source_email, later)

    def update(self, rows, email=None, **over):
        return update_supplier_quote(
            quotes=list(rows), data=self.data(**over), user=self.user, email=email)

    def test_cards_carry_the_source_for_the_tray(self):
        self.phone(contact_name='Sam', received_on=timezone.localdate().isoformat())
        card = saved_cards(self.supplier, [self.sol])[self.sol.solicitation_number][0]
        self.assertEqual((card['channel'], card['fields']['channel'], card['fields']['contact']), ('PHONE', 'PHONE', 'Sam'))
        self.assertEqual(card['fields']['received_on'], timezone.localdate().isoformat())
        self.assertTrue(card['via'].startswith('Phone'))
        self.assertIsNone(card['source_email_id'])


class DeleteTests(ManualBase):
    def test_removes_the_whole_quote_and_re_picks_the_lowest(self):
        cheap = self.log(supplier=self.apex, supplier_unit_cost='30')['quotes']
        mine = self.log(supplier_unit_cost='20')['quotes']
        self.assertTrue(QuoteSupplierQuote.objects.get(pk=mine[0].pk).is_selected_for_bid)
        self.assertEqual(delete_quotes(quotes_for_entry(self.supplier, self.sol, mine[0].entry)), 2)
        self.assertFalse(QuoteSupplierQuote.objects.filter(supplier=self.supplier).exists())
        self.assertTrue(QuoteSupplierQuote.objects.get(pk=cheap[0].pk).is_selected_for_bid)

    def test_the_supplier_is_waiting_again_on_the_lines_it_no_longer_has(self):
        rfq = self.rfq(self.line1)
        rows = self.phone(lines=[self.line1])['quotes']
        rfq.refresh_from_db()
        self.assertEqual(rfq.status, QuoteRFQ.STATUS_RESPONDED)
        delete_quotes(rows)
        rfq.refresh_from_db()
        self.assertEqual((rfq.status, rfq.response_received_at), (QuoteRFQ.STATUS_SENT, None))

    def test_a_quote_with_a_bid_on_it_cannot_be_removed(self):
        rows = self.log()['quotes']
        bid = self.bid(rows[0], QuoteBid.STATUS_DRAFT)
        with self.assertRaises(QuoteInputError) as ctx:
            delete_quotes(rows)
        self.assertIn('Bid Board', str(ctx.exception))
        bid.bid_status = QuoteBid.STATUS_SUBMITTED
        bid.submitted_at = timezone.now()
        bid.save()
        with self.assertRaises(QuoteLockedError):
            delete_quotes(rows)
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        with self.assertRaises(QuoteInputError):
            delete_quotes([])


class WaitingTests(ManualBase):
    def waiting(self, **kw):
        return quote_review.waiting_groups(**kw)

    def test_an_rfq_with_no_quote_is_waiting_grouped_per_solicitation_and_supplier(self):
        self.rfq(self.line1, days_ago=4)
        self.rfq(self.line2, days_ago=2)
        self.rfq(self.line1, supplier=self.apex, days_ago=1)
        groups = self.waiting()
        self.assertEqual([(g['supplier'].name, len(g['lines']), g['qty'], g['days_waiting'], g['state']) for g in groups],
                         [('Apex Fasteners', 1, 2, 1, 'waiting'), ('Vortex Tactical', 2, 5, 4, 'waiting')])
        self.assertEqual(groups[1]['days_to_due'], 20)

    def test_a_quote_takes_the_supplier_off_the_list_but_only_for_that_line(self):
        self.rfq(self.line1); self.rfq(self.line2)
        self.phone(lines=[self.line1])
        (group,) = self.waiting()
        self.assertEqual([line.pk for line in group['lines']], [self.line2.pk])
        self.phone(lines=[self.line2])
        self.assertEqual(self.waiting(), [])

    def test_another_suppliers_quote_does_not_answer_the_rfq(self):
        self.rfq(self.line1)
        self.log(supplier=self.apex, lines=[self.line1])
        self.assertEqual(len(self.waiting()), 1)

    def test_a_reply_that_nobody_entered_yet_is_flagged_and_linked(self):
        self.rfq(self.line1)
        reply, _ = mailbox.ingest_message(self.payload(id='r1', receivedDateTime=(timezone.now() + timedelta(hours=1)).isoformat()))
        (group,) = self.waiting()
        self.assertEqual((group['state'], group['reply_email_id']), ('replied', reply.pk))

    def test_closed_out_suppliers_only_show_when_asked(self):
        self.rfq(self.line1, status=QuoteRFQ.STATUS_NO_RESPONSE)
        self.assertEqual(self.waiting(), [])
        (group,) = self.waiting(include_closed=True)
        self.assertEqual((group['state'], group['status']), ('closed', QuoteRFQ.STATUS_NO_RESPONSE))

    def test_finished_and_past_due_solicitations_drop_off(self):
        self.rfq(self.line1)
        state = QuoteSolicitation.objects.get(solicitation=self.sol)
        for finished in (QuoteSolicitation.STATUS_NO_BID, QuoteSolicitation.STATUS_ARCHIVED,
                         QuoteSolicitation.STATUS_BID_SUBMITTED):
            state.set_status(finished); state.save()
            self.assertEqual(self.waiting(), [], finished)
        state.set_status(QuoteSolicitation.STATUS_RFQ_SENT); state.save()
        self.assertEqual(len(self.waiting()), 1)
        Solicitation.objects.filter(pk=self.sol.pk).update(return_by_date=timezone.localdate() - timedelta(days=2))
        self.assertEqual(self.waiting(), [])
        self.assertEqual(len(self.waiting(include_past_due=True)), 1)

    def test_queued_rfqs_are_not_waiting_yet(self):
        self.rfq(self.line1, status=QuoteRFQ.STATUS_QUEUED)
        self.assertEqual(self.waiting(), [])

    def test_close_and_reopen(self):
        r1, r2 = self.rfq(self.line1), self.rfq(self.line2)
        self.assertEqual(quote_review.close_rfqs(self.sol, self.supplier, QuoteRFQ.STATUS_DECLINED, ' Out of stock ', self.user), 2)
        for r in (r1, r2):
            r.refresh_from_db()
            self.assertEqual((r.status, r.declined_reason, r.modified_by), (QuoteRFQ.STATUS_DECLINED, 'Out of stock', self.user))
        self.assertEqual(self.waiting(), [])
        self.assertEqual(quote_review.reopen_rfqs(self.sol, self.supplier, self.user), 2)
        r1.refresh_from_db()
        self.assertEqual((r1.status, r1.declined_reason), (QuoteRFQ.STATUS_SENT, ''))
        self.assertEqual(len(self.waiting()), 1)
        quote_review.close_rfqs(self.sol, self.supplier, QuoteRFQ.STATUS_NO_RESPONSE, 'ignored', self.user)
        r1.refresh_from_db()
        self.assertEqual((r1.status, r1.declined_reason), (QuoteRFQ.STATUS_NO_RESPONSE, ''))     # a reason only rides on "declined"

    def test_close_and_reopen_refuse_when_there_is_nothing_to_do(self):
        with self.assertRaises(QuoteInputError):
            quote_review.close_rfqs(self.sol, self.supplier, QuoteRFQ.STATUS_DECLINED, '', self.user)
        with self.assertRaises(QuoteInputError):
            quote_review.reopen_rfqs(self.sol, self.supplier, self.user)
        self.rfq(self.line1)
        with self.assertRaises(QuoteInputError):
            quote_review.close_rfqs(self.sol, self.supplier, 'SENT', '', self.user)

    def test_a_quoted_line_is_not_closed_out(self):
        self.rfq(self.line1); self.rfq(self.line2)
        self.phone(lines=[self.line1])
        self.assertEqual(quote_review.close_rfqs(self.sol, self.supplier, QuoteRFQ.STATUS_NO_RESPONSE, '', self.user), 1)
        self.assertEqual(QuoteRFQ.objects.get(line=self.line1).status, QuoteRFQ.STATUS_RESPONDED)

    def test_the_enter_a_quote_picker_lists_who_we_asked(self):
        self.rfq(self.line1)
        self.rfq(self.line1, supplier=self.apex, status=QuoteRFQ.STATUS_DECLINED)
        self.phone(lines=[self.line1])
        got = {s['name']: s['state'] for s in quote_review.solicitation_suppliers(self.sol)}
        self.assertEqual(got, {'Apex Fasteners': 'closed', 'Vortex Tactical': 'quoted'})


class LoggedTests(ManualBase):
    def test_pending_quotes_by_default_with_sent_ones_on_request(self):
        rows = self.log()['quotes']
        self.phone(supplier=self.apex, lines=[self.line1], supplier_unit_cost='31')
        self.bid(rows[0], QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(), exported_bq_file='bq260929-101500.txt')
        pending = quote_review.logged_cards()
        self.assertEqual([(c['supplier'], c['covers']) for _sol, c in pending], [('Apex Fasteners', 'Line 0001')])
        everything = quote_review.logged_cards(include_sent=True)
        self.assertEqual({c['supplier'] for _sol, c in everything}, {'Apex Fasteners', 'Vortex Tactical'})
        self.assertTrue(next(c for _s, c in everything if c['supplier'] == 'Vortex Tactical')['locked'])

    def test_cards_come_soonest_due_first_and_past_due_is_left_out(self):
        other = Solicitation.objects.create(
            solicitation_number='SPE1C126Q0999', return_by_date=timezone.localdate() + timedelta(days=5),
            import_batch=self.sol.import_batch)
        line = SolicitationLine.objects.create(solicitation=other, nsn='5305-00-111-2222', fsc='5305', quantity=4,
                                               unit_of_issue='EA', line_number='0001')
        seed_solicitation_states([other.pk])
        save_supplier_quote(solicitation=other, supplier=self.supplier, lines=[line], data=self.data(), user=self.user, email=None)
        self.log()
        self.assertEqual([sol.solicitation_number for sol, _c in quote_review.logged_cards()],
                         ['SPE1C126Q0999', 'SPE1C126Q0528'])
        Solicitation.objects.filter(pk=other.pk).update(return_by_date=timezone.localdate() - timedelta(days=1))
        self.assertEqual([sol.solicitation_number for sol, _c in quote_review.logged_cards()], ['SPE1C126Q0528'])
        self.assertEqual(len(quote_review.logged_cards(include_past_due=True)), 2)

    def test_a_supplier_with_two_rows_on_a_line_is_flagged_as_a_duplicate(self):
        rows = self.log(lines=[self.line1])['quotes']
        QuoteSupplierQuote.objects.create(
            line=self.line1, supplier=self.supplier, nsn=rows[0].nsn, supplier_unit_cost=Decimal('50'),
            lead_time_days=10, final_government_unit_price=Decimal('51'), entry='legacy')
        self.assertTrue(all(c['duplicate'] for _sol, c in quote_review.logged_cards()))
        delete_quotes(quotes_for_entry(self.supplier, self.sol, 'legacy'))
        self.assertFalse(any(c['duplicate'] for _sol, c in quote_review.logged_cards()))
