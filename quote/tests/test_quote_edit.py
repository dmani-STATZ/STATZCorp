"""Editing a logged quote: one quote = one entry, updated in place, locked once its bid went to DIBBS."""
import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from dibbs.models import Solicitation, SolicitationLine
from quote.models import QuoteBid, QuoteEmail, QuoteSolicitation, QuoteSupplierQuote
from quote.services import bids as bid_service
from quote.services import mailbox
from quote.services.matching import seed_solicitation_states
from quote.services.quotes import (
    QuoteInput,
    QuoteInputError,
    QuoteLockedError,
    _reselect_lowest,
    quotes_for_entry,
    save_supplier_quote,
    saved_cards,
    update_supplier_quote,
)
from quote.tests.test_phase2 import MailboxBase
from suppliers.models import Supplier

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class EditBase(MailboxBase):
    """MailboxBase: SOL SPE1C126Q0528 with line 0001 (qty 2) and 0002 (qty 3), supplier Vortex."""

    def setUp(self):
        super().setUp()
        self.email, _ = mailbox.ingest_message(self.payload())
        self.lines = [self.line1, self.line2]

    def data(self, **over):
        base = dict(supplier_unit_cost='32.50', lead_time_days='45', markup_pct='2')
        base.update(over)
        return QuoteInput(**base)

    def log(self, lines=None, email=None, supplier=None, **over):
        return save_supplier_quote(
            solicitation=self.sol, supplier=supplier or self.supplier, lines=lines or self.lines,
            data=self.data(**over), user=self.user, email=email or self.email,
        )

    def edit(self, rows, email=None, **over):
        return update_supplier_quote(quotes=rows, data=self.data(**over), user=self.user, email=email or self.email)

    def cards(self, supplier=None):
        """The supplier's cards on the SOL (Vortex by default)."""
        return saved_cards(supplier or self.supplier, [self.sol]).get(self.sol.solicitation_number, [])

    def bid(self, quote, status, **extra):
        return QuoteBid.objects.create(
            line=quote.line, selected_quote=quote, quoter_cage='0SKY9', quote_for_cage='0SKY9',
            unit_price=quote.final_government_unit_price, delivery_days=quote.lead_time_days,
            manufacturer_dealer='DD', bid_status=status, **extra,
        )


class EntryTests(EditBase):
    def test_one_save_is_one_entry_across_its_lines(self):
        first = self.log()['quotes']
        self.assertEqual(len({q.entry for q in first}), 1)
        self.assertTrue(first[0].entry)
        # Re-quoting one line moves that line to the new save's entry; the other keeps the old one, so
        # the supplier's two lines are now two quotes (never two rows on one line).
        second = self.log(lines=[self.line1], supplier_unit_cost='40')['quotes']
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        entries = {q.line_id: q.entry for q in QuoteSupplierQuote.objects.all()}
        self.assertEqual(entries[self.line2.pk], first[0].entry)
        self.assertEqual(entries[self.line1.pk], second[0].entry)
        self.assertNotEqual(first[0].entry, second[0].entry)
        self.assertEqual([c['covers'] for c in self.cards()], ['Line 0001', 'Line 0002'])

    def test_saved_cards_describe_each_quote_as_the_drawer_needs_it(self):
        self.log(freight_total='50', packaging_unit='0.30', payment_terms='Net 30', notes='first pass',
                 offered_part_number='ZP1', offered_cage='0SKY9')
        other = Supplier.objects.create(name='Apex', cage_code='72914')
        self.log(lines=[self.line1], supplier=other, supplier_unit_cost='40', target_price='45.00')
        combined, = self.cards()
        split, = self.cards(other)
        self.assertEqual((combined['covers'], combined['covers_all'], combined['line_ids']),
                         ('All lines', True, [self.line1.pk, self.line2.pk]))
        f = combined['fields']
        # What was typed comes back as typed: freight as a total, packaging per unit.
        self.assertEqual((f['freight_typed'], f['freight_value']), ('total', '50.00'))
        self.assertEqual((f['pack_typed'], f['pack_value']), ('unit', '0.30'))
        self.assertEqual((f['cost'], f['lead'], f['part'], f['terms'], f['notes']),
                         ('32.50', '45', 'ZP1', 'Net 30', 'first pass'))
        self.assertEqual((f['markup_type'], f['markup_value']), ('PCT', '2'))
        # (32.50 cost + 0.30 packaging + 50 / qty 5 freight) x 1.02
        self.assertEqual((combined['cost'], combined['price'], combined['days']), ('32.50', '43.66', 45))
        # A price typed instead of a percentage comes back as that price, on just that line.
        self.assertEqual((split['covers'], split['covers_all']), ('Line 0001', False))
        self.assertEqual((split['fields']['markup_type'], split['fields']['markup_value']), ('FIXED', '45.00'))
        self.assertEqual(split['fields']['freight_typed'], None)
        self.assertTrue(combined['rev'] and not combined['locked'])
        self.assertEqual((combined['channel'], combined['via'].split(' · ')[0]), ('EMAIL', 'Email'))

    def test_whole_percent_markups_never_come_back_in_exponent_form(self):
        self.log(markup_pct='20')
        self.assertEqual(self.cards()[0]['fields']['markup_value'], '20')

    def test_cards_follow_the_supplier_not_the_message(self):
        other_email, _ = mailbox.ingest_message(self.payload(id='other', subject='RE: SPE1C126Q0528'))
        self.log(email=other_email)                                   # logged from a different message
        apex = Supplier.objects.create(name='Apex', cage_code='72914')
        self.log(supplier=apex, supplier_unit_cost='31')
        self.assertEqual(len(self.cards()), 1)                        # Vortex's, from either message
        self.assertEqual(self.cards()[0]['supplier'], 'Vortex Tactical')
        self.assertEqual(self.cards()[0]['source_email_id'], other_email.pk)
        self.assertEqual(saved_cards(None, [self.sol]), {})
        self.assertEqual(saved_cards(self.supplier, []), {})

    def test_older_rows_without_an_entry_are_grouped_by_their_numbers(self):
        rows = self.log()['quotes']
        QuoteSupplierQuote.objects.update(entry='')            # as saved before entries existed
        cards = self.cards()
        self.assertEqual([len(c['ids']) for c in cards], [2])
        key = cards[0]['entry']
        self.assertTrue(key.startswith('L'))
        self.assertEqual({q.pk for q in quotes_for_entry(self.supplier, self.sol, key)}, {rows[0].pk, rows[1].pk})
        # First edit pins the group with a real key.
        self.edit(quotes_for_entry(self.supplier, self.sol, key), supplier_unit_cost='31')
        self.assertFalse(self.cards()[0]['entry'].startswith('L'))
        self.assertEqual(len({q.entry for q in QuoteSupplierQuote.objects.all()}), 1)
        # Rows whose numbers differ are separate quotes.
        QuoteSupplierQuote.objects.update(entry='')
        QuoteSupplierQuote.objects.filter(line=self.line1).update(supplier_unit_cost=Decimal('40'))
        self.assertEqual([len(c['ids']) for c in self.cards()], [1, 1])

    def test_a_key_from_another_supplier_or_sol_finds_nothing(self):
        self.log()
        entry = self.cards()[0]['entry']
        apex = Supplier.objects.create(name='Apex', cage_code='72914')
        self.assertEqual(quotes_for_entry(apex, self.sol, entry), [])
        self.assertEqual(quotes_for_entry(self.supplier, self.sol, 'nope'), [])
        self.assertEqual(quotes_for_entry(None, self.sol, entry), [])


class UpdateTests(EditBase):
    def test_edits_the_same_rows_in_place(self):
        before = self.log(freight_total='50')['quotes']
        ids = sorted(q.pk for q in before)
        rows = quotes_for_entry(self.supplier, self.sol, before[0].entry)
        result = self.edit(rows, supplier_unit_cost='33.00', lead_time_days='40', freight_total='50', notes='second pass')
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)                 # no duplicate
        after = QuoteSupplierQuote.objects.order_by('pk')
        self.assertEqual([q.pk for q in after], ids)
        for q in after:
            self.assertEqual((q.supplier_unit_cost, q.lead_time_days, q.notes), (Decimal('33.00000'), 40, 'second pass'))
            self.assertEqual(q.freight_adder_unit, Decimal('10.00000'))         # 50 over qty 2 + 3
            self.assertEqual(q.final_government_unit_price, Decimal('43.86000'))  # (33 + 10) x 1.02
            self.assertEqual((q.modified_by, q.entered_by, q.entry), (self.user, self.user, before[0].entry))
        self.assertEqual(result['price'], Decimal('43.86'))

    def test_totals_spread_over_the_quotes_own_lines_not_the_whole_sol(self):
        split = self.log(lines=[self.line1], freight_total='50')['quotes']
        self.assertEqual(split[0].freight_adder_unit, Decimal('25.00000'))      # over qty 2
        self.edit(split, freight_total='60')
        split[0].refresh_from_db()
        self.assertEqual(split[0].freight_adder_unit, Decimal('30.00000'))

    def test_editing_one_quote_leaves_the_others_alone(self):
        one = self.log(lines=[self.line1], supplier_unit_cost='32.50')['quotes']
        two = self.log(lines=[self.line2], supplier_unit_cost='30')['quotes']       # a separate per-line quote
        apex = Supplier.objects.create(name='Apex', cage_code='72914')
        theirs = self.log(lines=[self.line2], supplier=apex, supplier_unit_cost='29')['quotes']
        self.edit(two, supplier_unit_cost='31')
        self.assertEqual(QuoteSupplierQuote.objects.get(pk=one[0].pk).supplier_unit_cost, Decimal('32.50000'))
        self.assertEqual(QuoteSupplierQuote.objects.get(pk=theirs[0].pk).supplier_unit_cost, Decimal('29.00000'))
        self.assertEqual(QuoteSupplierQuote.objects.get(pk=two[0].pk).supplier_unit_cost, Decimal('31.00000'))

    def test_a_rejected_edit_changes_nothing(self):
        rows = self.log()['quotes']
        for bad in ({'lead_time_days': '0'}, {'offered_cage': 'ABC'}, {'supplier_unit_cost': 'abc'},
                    {'supplier_unit_cost': '10', 'target_price': '5'}):
            with self.assertRaises((QuoteInputError, ValueError), msg=str(bad)):
                self.edit(rows, **bad)
        self.assertEqual({q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}, {Decimal('32.50000')})
        with self.assertRaises(QuoteInputError):
            update_supplier_quote(quotes=[], data=self.data(), user=self.user)

    def test_the_lowest_landed_quote_is_re_picked_after_an_edit(self):
        other = Supplier.objects.create(name='Apex', cage_code='72914')
        cheap = self.log(lines=[self.line1], supplier=other, supplier_unit_cost='30')['quotes']
        dear = self.log(lines=[self.line1], supplier_unit_cost='40')['quotes']
        self.assertTrue(QuoteSupplierQuote.objects.get(pk=cheap[0].pk).is_selected_for_bid)
        self.edit(dear, supplier_unit_cost='20')
        picked = QuoteSupplierQuote.objects.get(line=self.line1, is_selected_for_bid=True)
        self.assertEqual(picked.pk, dear[0].pk)
        self.assertTrue(picked.selected_automatically)


class LockTests(EditBase):
    def sent(self, quote):
        return self.bid(quote, QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(),
                        exported_bq_file='bq260929-101500.txt')

    def test_a_quote_whose_bid_went_to_dibbs_cannot_be_changed(self):
        rows = self.log()['quotes']
        self.sent(rows[0])
        with self.assertRaises(QuoteLockedError) as ctx:
            self.edit(rows, supplier_unit_cost='1')
        self.assertIn('bq260929-101500.txt', str(ctx.exception))
        self.assertIn('Bid Board', str(ctx.exception))
        self.assertEqual({q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}, {Decimal('32.50000')})

    def test_the_lock_covers_the_whole_quote_and_shows_on_its_card(self):
        rows = self.log()['quotes']
        self.sent(rows[1])                                     # only the second line's bid was sent
        card = self.cards()[0]
        self.assertTrue(card['locked'])
        self.assertIn('sent to DIBBS', card['lock_reason'])
        with self.assertRaises(QuoteLockedError):
            self.edit(rows)

    def test_a_bid_sent_on_a_different_quote_does_not_lock_this_one(self):
        other = Supplier.objects.create(name='Apex', cage_code='72914')
        theirs = self.log(lines=[self.line1], supplier=other, supplier_unit_cost='30')['quotes']
        mine = self.log(lines=[self.line1])['quotes']
        self.sent(theirs[0])
        self.edit(mine, supplier_unit_cost='31')               # allowed: its own bid was not sent
        self.assertTrue(self.cards(other)[0]['locked'])        # the sent one is read-only ...
        mine_card = self.cards()[0]
        self.assertFalse(mine_card['locked'])                  # ... this one is not
        self.assertEqual(mine_card['cost'], '31.00')

    def test_bids_in_progress_are_described_and_do_not_lock(self):
        rows = self.log()['quotes']
        card = lambda: self.cards()[0]      # noqa: E731
        self.assertIn('Not on a bid yet', card()['bid_note'])
        bid = self.bid(rows[0], QuoteBid.STATUS_DRAFT)
        self.assertIn('being built', card()['bid_note'])
        bid.bid_status = QuoteBid.STATUS_READY
        bid.save()
        self.assertIn('back to Needs bid', card()['bid_note'])
        self.assertFalse(card()['locked'])

    def test_a_line_already_sent_keeps_its_chosen_quote_when_others_are_added(self):
        other = Supplier.objects.create(name='Apex', cage_code='72914')
        sent = self.log(lines=[self.line1], supplier_unit_cost='40')['quotes']
        self.sent(sent[0])
        self.log(lines=[self.line1], supplier=other, supplier_unit_cost='10')      # much cheaper, later
        self.assertTrue(QuoteSupplierQuote.objects.get(pk=sent[0].pk).is_selected_for_bid)
        _reselect_lowest(self.line1)
        self.assertEqual(QuoteSupplierQuote.objects.filter(line=self.line1, is_selected_for_bid=True).count(), 1)


class BidFollowTests(EditBase):
    def setUp(self):
        super().setUp()
        self.rows = self.log()['quotes']            # 32.50 + 0 -> 33.15 at 2%, 45 days
        self.q1 = self.rows[0]

    def test_a_draft_bid_still_carrying_the_old_price_follows_the_quote(self):
        bid = self.bid(self.q1, QuoteBid.STATUS_DRAFT)
        result = self.edit(self.rows, supplier_unit_cost='34.00', lead_time_days='30')
        bid.refresh_from_db()
        self.assertEqual((bid.unit_price, bid.delivery_days, bid.bid_status),
                         (Decimal('34.68000'), 30, QuoteBid.STATUS_DRAFT))
        self.assertEqual(bid.margin_pct, Decimal('2.00'))
        self.assertTrue(any('now bids $34.68' in n and 'now 30 days' in n for n in result['bid_notes']), result['bid_notes'])

    def test_a_price_the_rep_set_on_the_bid_by_hand_is_kept_and_they_are_told(self):
        bid = self.bid(self.q1, QuoteBid.STATUS_DRAFT)
        QuoteBid.objects.filter(pk=bid.pk).update(unit_price=Decimal('40.00000'))
        result = self.edit(self.rows, supplier_unit_cost='34.00')
        bid.refresh_from_db()
        self.assertEqual(bid.unit_price, Decimal('40.00000'))
        self.assertTrue(any('kept the price set on the bid' in n for n in result['bid_notes']))

    def test_a_ready_bid_goes_back_to_needs_bid_and_so_does_its_solicitation(self):
        bid = self.bid(self.q1, QuoteBid.STATUS_READY)
        state, _ = QuoteSolicitation.objects.get_or_create(solicitation=self.sol)
        state.set_status(QuoteSolicitation.STATUS_BID_READY)
        state.save()
        result = self.edit(self.rows, supplier_unit_cost='34.00')
        bid.refresh_from_db()
        self.assertEqual(bid.bid_status, QuoteBid.STATUS_DRAFT)
        state.refresh_from_db()
        self.assertEqual(state.status, QuoteSolicitation.STATUS_QUOTING)
        self.assertTrue(any('back in Needs bid' in n for n in result['bid_notes']))

    def test_an_edit_that_changes_nothing_the_bid_uses_leaves_a_ready_bid_ready(self):
        bid = self.bid(self.q1, QuoteBid.STATUS_READY)
        self.edit(self.rows, notes='just a note')
        bid.refresh_from_db()
        self.assertEqual(bid.bid_status, QuoteBid.STATUS_READY)

    def test_a_changed_part_number_is_flagged_because_the_bid_still_lists_the_old_one(self):
        self.bid(self.q1, QuoteBid.STATUS_READY)
        result = self.edit(self.rows, offered_part_number='NEW-PN')
        self.assertTrue(any('old part number' in n for n in result['bid_notes']), result['bid_notes'])
        self.assertEqual(QuoteBid.objects.get().bid_status, QuoteBid.STATUS_DRAFT)

    def test_helper_never_touches_a_sent_bid(self):
        bid = self.bid(self.q1, QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now())
        notes = bid_service.sync_after_quote_edit(
            self.q1, (Decimal('1'), 1, '', ''), self.user)
        bid.refresh_from_db()
        self.assertEqual((notes, bid.unit_price, bid.bid_status), ([], self.q1.final_government_unit_price, 'SUBMITTED'))


class EditViewTests(EditBase):
    def post(self, **fields):
        data = {'sol': self.sol.solicitation_number, 'supplier_id': self.supplier.pk, 'unit_cost': '32.50',
                'lead_time_days': '45', 'markup_pct': '2', 'mode': 'combined'}
        data.update(fields)
        return self.client.post(reverse('quote:save_quote', args=[self.email.pk]), data, **XHR)

    def detail(self):
        return self.client.get(reverse('quote:email_detail', args=[self.email.pk]), **XHR)

    def test_saving_a_new_quote_then_updating_it_never_duplicates(self):
        self.assertTrue(self.post().json()['ok'])
        entry = self.cards()[0]['entry']
        resp = self.post(entry=entry, unit_cost='33.00', freight_total='10')
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body['message'].startswith('Updated Vortex Tactical at $'), body['message'])
        self.assertEqual(QuoteSupplierQuote.objects.count(), 2)
        self.assertEqual({q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}, {Decimal('33.00000')})

    def test_the_form_mode_cannot_change_which_lines_an_update_covers(self):
        self.post(mode='split', line_id=self.line1.pk)
        entry = self.cards()[0]['entry']
        self.post(entry=entry, unit_cost='31', mode='combined')          # form says combined; the quote is one line
        self.assertEqual(QuoteSupplierQuote.objects.count(), 1)
        self.assertEqual(QuoteSupplierQuote.objects.get().line, self.line1)

    def test_bad_keys_and_bad_numbers(self):
        self.post()
        entry = self.cards()[0]['entry']
        self.assertEqual(self.post(entry='nope').status_code, 404)
        apex = Supplier.objects.create(name='Apex', cage_code='72914')
        stray = self.post(entry=entry, supplier_id=apex.pk, unit_cost='1', lead_time_days='1')
        self.assertEqual(stray.status_code, 404)                          # another supplier's quote is not editable here
        bad = self.post(entry=entry, lead_time_days='0')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual({q.lead_time_days for q in QuoteSupplierQuote.objects.all()}, {45})

    def test_a_sent_quote_is_refused_with_a_409(self):
        self.post()
        rows = list(QuoteSupplierQuote.objects.all())
        QuoteBid.objects.create(
            line=rows[0].line, selected_quote=rows[0], quoter_cage='0SKY9', quote_for_cage='0SKY9',
            unit_price=rows[0].final_government_unit_price, delivery_days=45, manufacturer_dealer='DD',
            bid_status=QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(), exported_bq_file='bq260929-101500.txt')
        entry = rows[0].entry
        resp = self.post(entry=entry, unit_cost='1.00')
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.json()['locked'])
        self.assertIn('bq260929-101500.txt', resp.json()['error'])
        self.assertEqual({q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}, {Decimal('32.50000')})

    def test_the_update_message_reports_what_happened_to_a_bid_in_progress(self):
        self.post()
        rows = list(QuoteSupplierQuote.objects.order_by('pk'))
        QuoteBid.objects.create(
            line=rows[0].line, selected_quote=rows[0], quoter_cage='0SKY9', quote_for_cage='0SKY9',
            unit_price=rows[0].final_government_unit_price, delivery_days=45, manufacturer_dealer='DD',
            bid_status=QuoteBid.STATUS_READY)
        message = self.post(entry=rows[0].entry, unit_cost='34.00').json()['message']
        self.assertIn('back in Needs bid', message)

    def test_the_fragment_carries_the_cards_and_the_right_buttons(self):
        self.post()
        rows = list(QuoteSupplierQuote.objects.order_by('pk'))
        def table(html):
            return re.search(r'<div class="quote-msg-quotes">[\s\S]*?</table>', html).group(0)

        html = self.detail().content.decode()
        self.assertEqual(html.count('data-edit-quote'), 2)                # one per logged row
        self.assertIn(f'data-entry="{rows[0].entry}"', html)
        self.assertIn('bi-pencil', table(html))
        self.assertNotIn('bi-lock', table(html))
        self.assertRegex(html, r'"cards": \[\{"entry": "%s"' % rows[0].entry)
        for hook in ('id="qEntry"', 'id="qLockNote"', 'id="qScopeNote"', 'id="qFields"'):
            self.assertIn(hook, html)
        QuoteBid.objects.create(
            line=rows[0].line, selected_quote=rows[0], quoter_cage='0SKY9', quote_for_cage='0SKY9',
            unit_price=rows[0].final_government_unit_price, delivery_days=45, manufacturer_dealer='DD',
            bid_status=QuoteBid.STATUS_SUBMITTED, submitted_at=timezone.now(), exported_bq_file='bq260929-101500.txt')
        html = self.detail().content.decode()
        self.assertIn('bi-lock', table(html))                             # the row now says "Sent"
        self.assertNotIn('bi-pencil', table(html))
        self.assertRegex(html, r'"locked": true')

    def test_anonymous_visitors_cannot_update(self):
        self.post()
        entry = self.cards()[0]['entry']
        resp = Client().post(reverse('quote:save_quote', args=[self.email.pk]), {
            'sol': self.sol.solicitation_number, 'entry': entry, 'unit_cost': '1', 'lead_time_days': '1'})
        self.assertNotEqual(resp.status_code, 200)
        self.assertEqual({q.supplier_unit_cost for q in QuoteSupplierQuote.objects.all()}, {Decimal('32.50000')})


class TemplateSyntaxLeakTests(EditBase):
    """A {# #} comment that wraps onto a second line is printed on the page as text (it once was)."""

    def test_no_template_syntax_reaches_the_browser(self):
        self.log()
        frag = self.client.get(reverse('quote:email_detail', args=[self.email.pk]), **XHR).content.decode()
        page = self.client.get(reverse('quote:mailbox')).content.decode()
        for name, html in (('email_detail', frag), ('mailbox', page)):
            self.assertNotIn('{#', html, name)
            self.assertNotIn('#}', re.sub(r'<script[\s\S]*?</script>', '', html), name)
            self.assertNotIn('{%', html, name)
