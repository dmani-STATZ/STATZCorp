"""Phase 3: bid defaults, DIBBS pre-flight, template-preserving BQ writer, export, views."""
import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dibbs.models import ApprovedSource, CompanyCAGE, ImportBatch, Solicitation, SolicitationLine
from quote.models import BidOutcome, QuoteBid, QuoteSolicitation, QuoteSupplierQuote
from quote.services import bids
from quote.services.matching import seed_solicitation_states
from quote.services.quotes import QuoteInput, save_supplier_quote
from suppliers.models import Supplier


def dibbs_template(sol_number, nsn, qty, item_indicator='P'):
    """A realistic DIBBS BQ row: DIBBS pre-fills these defaults."""
    row = [''] * 121
    for col, value in {
        1: sol_number, 3: 'Y', 4: 'N', 5: '10/05/2026', 24: 'BI', 25: '1', 27: '90', 29: 'NAP',
        32: 'D', 36: 'D', 39: 'N', 44: '0001', 46: '7018302110', 47: nsn, 48: 'EA',
        49: str(qty), 51: '45', 57: 'N', 62: 'N', 68: 'N', 69: 'N', 73: 'N', 77: 'N',
        96: '0', 97: '0', 98: 'N', 100: 'N', 105: item_indicator, 117: 'N', 120: 'N',
    }.items():
        row[col - 1] = value
    return row


class Phase3Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('rep', 'rep@example.com', 'x', first_name='Dion')
        self.client.force_login(self.user)
        self.cage = CompanyCAGE.objects.create(
            cage_code='3WGD1', company_name='STATZ', sb_representations_code='B',
            affirmative_action_code='Y6', previous_contracts_code='Y4',
            alternate_disputes_resolution='A', is_default=True, is_active=True,
        )
        today = timezone.now().date()
        batch = ImportBatch.objects.create(import_date=today, imported_at=timezone.now())
        self.sol = self._sol('SPE1C126Q0528', today, batch)
        self.line = self.sol.lines.get()
        self.supplier = Supplier.objects.create(name='Vortex Tactical', cage_code='0SKY9')
        ApprovedSource.objects.create(nsn='8465016131241', approved_cage='0SKY9',
                                      part_number='ZPCARA101XX', import_batch=batch)

    def _sol(self, number, today, batch):
        sol = Solicitation.objects.create(
            solicitation_number=number, return_by_date=today + timedelta(days=20), import_batch=batch,
        )
        SolicitationLine.objects.create(
            solicitation=sol, nsn='8465-01-613-1241', fsc='8465', quantity=2, unit_of_issue='EA',
            line_number='0001', nomenclature='CARABINER', delivery_days=45,
            bq_raw_columns=dibbs_template(number, '8465-01-613-1241', 2),
        )
        seed_solicitation_states([sol.pk])
        return sol

    def _quote(self, supplier=None, cost='32.50', part='ZPCARA101XX', cage='0SKY9', lead='30'):
        return save_supplier_quote(
            solicitation=self.sol, supplier=supplier or self.supplier, lines=[self.line],
            data=QuoteInput(supplier_unit_cost=cost, lead_time_days=lead,
                            offered_part_number=part, offered_cage=cage, markup_pct='6'),
            user=self.user,
        )['quotes'][0]

    def _ready_bid(self, **overrides):
        self._quote()
        bid = bids.bid_for(self.line, self.user)
        for k, v in overrides.items():
            setattr(bid, k, v)
        bid.save()
        bid.bid_status = QuoteBid.STATUS_READY
        bid.save()
        return bid


class DefaultsAndPreflightTests(Phase3Base):
    def test_defaults_from_quote_cage_and_template(self):
        quote = self._quote()
        bid = bids.bid_for(self.line)
        self.assertEqual(bid.quoter_cage, '3WGD1')
        self.assertEqual(bid.unit_price, quote.final_government_unit_price)
        self.assertEqual(bid.delivery_days, 30)
        self.assertEqual(bid.manufacturer_dealer, 'DD')
        self.assertEqual(bid.mfg_source_cage, '0SKY9')
        self.assertEqual(bid.part_number_offered_code, '1')    # exact: in the AS file
        self.assertEqual(bid.bid_type_code, 'BI')
        self.assertEqual(bid.days_quote_valid, 90)

    def test_unapproved_part_defaults_to_alternate_bid(self):
        self._quote(part='OTHER-123')
        bid = bids.bid_for(self.line)
        self.assertEqual(bid.part_number_offered_code, '2')
        self.assertEqual(bid.bid_type_code, 'AB')

    def test_clean_bid_passes(self):
        self._quote()
        bid = bids.bid_for(self.line)
        bid.save()
        self.assertEqual([c for c in bids.preflight(bid) if c.level == 'error'], [])

    def _errors(self, **overrides):
        self._quote()
        bid = bids.bid_for(self.line)
        for k, v in overrides.items():
            setattr(bid, k, v)
        bid.save()
        return ' | '.join(c.message for c in bids.preflight(bid) if c.level == 'error')

    def test_auto_award_remarks_blocked(self):
        QuoteSolicitation.objects.all().delete()
        auto = self._sol('SPE4A626T36QG', timezone.now().date(), self.sol.import_batch)
        line = auto.lines.get()
        bid = bids.bid_for(line)
        bid.unit_price, bid.delivery_days = Decimal('10'), 30
        bid.part_number_offered, bid.part_number_offered_cage = 'ZPCARA101XX', '0SKY9'
        bid.part_number_offered_code, bid.mfg_source_cage = '1', '0SKY9'
        bid.bid_remarks = 'please consider'
        bid.save()
        self.assertIn('automated (T/U)', ' '.join(c.message for c in bids.preflight(bid)))

    def test_rules(self):
        self.assertIn('not an approved source', self._errors(part_number_offered='NOPE'))
        QuoteSupplierQuote.objects.all().delete(); QuoteBid.objects.all().delete()
        self.assertIn('must not carry remarks', self._errors(bid_remarks='x'))
        QuoteSupplierQuote.objects.all().delete(); QuoteBid.objects.all().delete()
        self.assertIn('forces a BW or AB', self._errors(meets_packaging_requirement='N'))
        QuoteSupplierQuote.objects.all().delete(); QuoteBid.objects.all().delete()
        self.assertIn("manufacturer's 5-character CAGE", self._errors(mfg_source_cage=''))
        QuoteSupplierQuote.objects.all().delete(); QuoteBid.objects.all().delete()
        self.assertIn('5 decimal places', self._errors(unit_price=Decimal('1.123456')))
        QuoteSupplierQuote.objects.all().delete(); QuoteBid.objects.all().delete()
        self.assertIn('part number and CAGE offered are required',
                      self._errors(part_number_offered='', part_number_offered_code=''))

    def test_long_delivery_is_a_warning(self):
        self._quote(lead='60')
        bid = bids.bid_for(self.line)
        bid.save()
        levels = {c.level for c in bids.preflight(bid) if 'longer than' in c.message}
        self.assertEqual(levels, {'warning'})


class WriterTests(Phase3Base):
    def test_row_preserves_template_and_overlays_ours(self):
        bid = self._ready_bid()
        row = bids.bq_row(bid)
        self.assertEqual(len(row), 121)
        self.assertEqual(row[0], 'SPE1C126Q0528')      # DIBBS cell untouched
        self.assertEqual(row[28], 'NAP')               # col 29 untouched
        self.assertEqual(row[5], '3WGD1')              # col 6 quoter CAGE
        self.assertEqual(row[12], 'B')                 # col 13 from CompanyCAGE
        self.assertEqual(row[49], f'{bid.unit_price:.5f}')  # col 50, 5 decimals
        self.assertEqual(row[50], '30')                # col 51 ours, not DIBBS's 45
        self.assertEqual(row[107], 'ZPCARA101XX')      # col 108, never padded
        self.assertEqual(row[120], '')                 # col 121 remarks

    def test_file_format(self):
        bid = self._ready_bid()
        content = bids.render_bq([bid])
        text = content.decode('iso-8859-1')
        self.assertTrue(text.endswith('\r\n'))
        self.assertTrue(text.startswith('"SPE1C126Q0528","'))
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual([len(r) for r in rows], [121])


class ExportTests(Phase3Base):
    def test_export_submits_snapshots_and_can_reopen(self):
        bid = self._ready_bid()
        filename, content = bids.export_bids([bid.pk], self.user)
        bid.refresh_from_db()
        self.assertEqual(bid.bid_status, 'SUBMITTED')
        self.assertEqual(bid.exported_bq_file, filename)
        outcome = BidOutcome.objects.get(bid=bid)
        self.assertEqual(outcome.snapshot_supplier_name, 'Vortex Tactical')
        self.assertEqual(outcome.our_unit_price, bid.unit_price)
        self.assertEqual(QuoteSolicitation.objects.get(solicitation=self.sol).status, 'BID_SUBMITTED')
        self.assertEqual(bids.reexport(filename), content)

        self.assertTrue(bids.reopen_bid(bid))
        bid.refresh_from_db()
        self.assertEqual(bid.bid_status, 'READY')
        self.assertFalse(BidOutcome.objects.filter(bid=bid).exists())

    def test_export_is_all_or_nothing(self):
        bid = self._ready_bid(bid_remarks='oops')
        with self.assertRaises(bids.BidExportError):
            bids.export_bids([bid.pk], self.user)
        bid.refresh_from_db()
        self.assertEqual(bid.bid_status, 'READY')

    def test_manual_pick_beats_auto_lowest(self):
        cheap_supplier = Supplier.objects.create(name='Apex', cage_code='72914')
        first = self._quote()
        self._quote(supplier=cheap_supplier, cost='10')
        bids.select_quote(first)
        self._quote(supplier=cheap_supplier, cost='5')
        self.assertEqual(QuoteSupplierQuote.objects.get(line=self.line, is_selected_for_bid=True), first)


class ViewTests(Phase3Base):
    def test_board_compare_builder_export(self):
        self._quote()
        for tab in ('needs', 'ready', 'submitted'):
            self.assertEqual(self.client.get(reverse('quote:bid_board'), {'tab': tab}).status_code, 200)
        resp = self.client.get(reverse('quote:compare_quotes', args=['SPE1C126Q0528']),
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(resp, 'Vortex Tactical')

        url = reverse('quote:bid_builder', args=['SPE1C126Q0528'])
        self.assertEqual(self.client.get(url).status_code, 200)
        p = f'l{self.line.pk}_'
        post = {
            'action': 'ready', 'h_quoter_cage': '3WGD1', 'h_quote_for_cage': '3WGD1',
            'h_bid_type_code': 'BI', 'h_payment_terms': '1', 'h_vendor_quote_number': 'Q1',
            'h_days_quote_valid': '90', 'h_meets_packaging_requirement': 'Y', 'h_fob_point': 'D',
            'h_inspection_point': 'D', 'h_bid_remarks': '',
            f'{p}unit_price': '36.50', f'{p}delivery_days': '30', f'{p}manufacturer_dealer': 'DD',
            f'{p}mfg_source_cage': '0SKY9', f'{p}part_number_offered_code': '1',
            f'{p}part_number_offered_cage': '0SKY9', f'{p}part_number_offered': 'ZPCARA101XX',
            f'{p}hazardous_material': 'N', f'{p}material_requirements': '0',
        }
        self.assertRedirects(self.client.post(url, post), reverse('quote:bid_board') + '?tab=ready')
        bid = QuoteBid.objects.get()
        self.assertEqual((bid.bid_status, bid.unit_price), ('READY', Decimal('36.50000')))

        self.assertEqual(self.client.get(reverse('quote:bid_export')).status_code, 200)
        resp = self.client.post(reverse('quote:bid_export'), {'bid_ids': [bid.pk]})
        self.assertEqual(resp['Content-Type'], 'text/plain; charset=iso-8859-1')
        self.assertIn('attachment; filename="bq', resp['Content-Disposition'])
        self.assertEqual(QuoteBid.objects.get().bid_status, 'SUBMITTED')
