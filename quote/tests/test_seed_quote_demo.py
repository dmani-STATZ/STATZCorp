"""
Tests for the dev-only demo seeder.

The two properties that actually matter:
  1. It refuses to run against production.
  2. --clear removes every row it created and nothing else. The dev database is
     a production-like copy, so a clear that over-reaches would destroy real
     solicitations, awards or product records.
"""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from products.models import Nsn
from dibbs.models import (
    ApprovedSource,
    DibbsAward,
    ImportBatch,
    Solicitation,
    SolicitationLine,
)
from suppliers.models import Supplier

from quote.models import (
    BidOutcome,
    QuoteBid,
    QuoteEmail,
    QuoteEmailAttachment,
    QuoteEmailSolLink,
    QuoteRFQ,
    QuoteSolicitation,
    QuoteSolicitationMatch,
    QuoteSupplierFSC,
    QuoteSupplierNSN,
    QuoteSupplierQuote,
)

COMMAND = 'seed_quote_demo'
MODULE = 'quote.management.commands.seed_quote_demo'


def _seed(**kwargs):
    out = StringIO()
    call_command(COMMAND, stdout=out, **kwargs)
    return out.getvalue()


class ProductionGuardTests(TestCase):
    def test_refuses_when_website_site_name_is_set(self):
        with mock.patch.dict('os.environ', {'WEBSITE_SITE_NAME': 'statzweb-prod'}):
            with self.assertRaises(CommandError) as ctx:
                _seed()

        self.assertIn('refuses to run against production', str(ctx.exception))

    def test_refuses_when_settings_is_production(self):
        with self.settings(IS_PRODUCTION=True):
            with self.assertRaises(CommandError) as ctx:
                _seed()

        self.assertIn('IS_PRODUCTION', str(ctx.exception))

    def test_guard_also_blocks_clear(self):
        # Nothing should have been seeded on prod, so clearing there is a sign
        # something is wrong -- block it too rather than quietly deleting rows.
        with self.settings(IS_PRODUCTION=True):
            with self.assertRaises(CommandError):
                _seed(clear=True)

    def test_runs_when_not_production(self):
        with self.settings(IS_PRODUCTION=False):
            _seed()

        self.assertTrue(Solicitation.objects.exists())


class SeedContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _seed()

    def test_covers_every_pipeline_stage(self):
        statuses = set(
            QuoteSolicitation.objects.values_list('status', flat=True)
        )
        # Unworked, matched, sent, and bid-submitted must all appear or the
        # demo does not actually show the workflow.
        self.assertEqual(
            statuses,
            {
                QuoteSolicitation.STATUS_UNMATCHED,
                QuoteSolicitation.STATUS_MATCHED,
                QuoteSolicitation.STATUS_RFQ_SENT,
                QuoteSolicitation.STATUS_BID_SUBMITTED,
            },
        )
        # Every demo solicitation carries workflow state.
        self.assertEqual(QuoteSolicitation.objects.count(), Solicitation.objects.count())

    def test_covers_every_outcome_including_a_near_miss(self):
        outcomes = dict(
            (o, BidOutcome.objects.filter(outcome=o).count())
            for o in ('WON', 'LOST', 'PENDING')
        )
        self.assertEqual(outcomes['WON'], 2)
        self.assertEqual(outcomes['LOST'], 3)
        self.assertEqual(outcomes['PENDING'], 1)

        # The "Within 5%" missed-opportunity counter needs data.
        self.assertEqual(BidOutcome.objects.filter(within_5_pct=True).count(), 2)

    def test_cost_buildup_is_internally_consistent(self):
        from decimal import Decimal

        for quote in QuoteSupplierQuote.objects.all():
            expected = (
                quote.landed_unit_cost
                * (Decimal('1') + quote.markup_value / Decimal('100'))
            ).quantize(Decimal('0.00001'))
            self.assertEqual(
                quote.final_government_unit_price, expected,
                f'{quote.supplier.name}: final price does not match the buildup',
            )

    def test_one_email_links_to_multiple_solicitations(self):
        # The consolidated-RFQ reply case the mailbox workspace has to handle.
        multi = [
            email for email in QuoteEmail.objects.all()
            if email.sol_links.count() > 1
        ]
        self.assertTrue(multi, 'no email covering more than one solicitation')
        self.assertEqual(multi[0].sol_links.count(), 2)

    def test_has_an_orphan_email_with_no_solicitation(self):
        orphans = QuoteEmail.objects.filter(is_orphan=True)
        self.assertTrue(orphans.exists())
        self.assertEqual(orphans.first().sol_links.count(), 0)

    def test_has_competing_quotes_with_lowest_auto_selected(self):
        contested = [
            line for line in SolicitationLine.objects.all()
            if line.quote_supplier_quotes.count() > 1
        ]
        self.assertTrue(contested, 'no line has competing quotes to compare')

        line = contested[0]
        quotes = list(line.quote_supplier_quotes.all())
        selected = [q for q in quotes if q.is_selected_for_bid]

        self.assertEqual(len(selected), 1)
        self.assertEqual(
            selected[0].final_government_unit_price,
            min(q.final_government_unit_price for q in quotes),
            'the auto-selected quote is not the lowest',
        )
        self.assertTrue(selected[0].selected_automatically)

    def test_bq_template_is_121_columns(self):
        for line in SolicitationLine.objects.all():
            self.assertEqual(len(line.bq_raw_columns), 121)
            self.assertEqual(
                line.bq_raw_columns[0], line.solicitation.solicitation_number,
            )

    def test_seeds_a_packhouse_and_uses_it(self):
        packhouse = Supplier.objects.filter(is_packhouse=True).first()
        self.assertIsNotNone(packhouse)
        self.assertTrue(
            QuoteSupplierQuote.objects.filter(packaging_vendor=packhouse).exists(),
            'packhouse supplier is never referenced by a quote',
        )

    def test_is_idempotent(self):
        before = Solicitation.objects.count()
        _seed()

        self.assertEqual(Solicitation.objects.count(), before)


class ClearIsolationTests(TestCase):
    """--clear must remove demo rows and leave everything else alone."""

    def setUp(self):
        # Stand in for the real data a dev database is full of. None of this
        # carries a demo marker, so none of it may be deleted.
        self.real_batch = ImportBatch.objects.create(
            import_date='2026-01-05', imported_at='2026-01-05T09:00:00Z',
            imported_by='a_real_human',
        )
        self.real_sol = Solicitation.objects.create(
            solicitation_number='SPE1C126Q9999', import_batch=self.real_batch,
        )
        SolicitationLine.objects.create(
            solicitation=self.real_sol, nsn='1234-01-000-0000',
        )
        self.real_award = DibbsAward.objects.create(
            sol_number='SPE1C126Q9999', notice_id='REAL-NOTICE-1',
            award_date='2026-01-10',
        )
        self.real_supplier = Supplier.objects.create(
            name='A Real Supplier', cage_code='REAL1', notes='genuine record',
        )
        self.real_nsn = Nsn.objects.create(
            nsn_code='1234-01-000-0000', description='REAL PART',
            dimension_source_notes='measured on the bench',
        )
        self.real_as = ApprovedSource.objects.create(
            nsn='1234010000000', approved_cage='REAL1',
            import_batch=self.real_batch,
        )

    def test_clear_removes_all_demo_rows(self):
        _seed()
        _seed(clear=True)

        for model in (QuoteRFQ, QuoteSupplierQuote, QuoteBid, BidOutcome,
                      QuoteEmail, QuoteEmailAttachment, QuoteEmailSolLink,
                      QuoteSolicitation, QuoteSolicitationMatch,
                      QuoteSupplierNSN, QuoteSupplierFSC):
            self.assertEqual(
                model.objects.count(), 0,
                f'{model.__name__} still has rows after --clear',
            )

    def test_clear_preserves_every_non_demo_row(self):
        _seed()
        _seed(clear=True)

        self.assertTrue(Solicitation.objects.filter(pk=self.real_sol.pk).exists())
        self.assertTrue(ImportBatch.objects.filter(pk=self.real_batch.pk).exists())
        self.assertTrue(DibbsAward.objects.filter(pk=self.real_award.pk).exists())
        self.assertTrue(Supplier.objects.filter(pk=self.real_supplier.pk).exists())
        self.assertTrue(Nsn.objects.filter(pk=self.real_nsn.pk).exists())
        self.assertTrue(ApprovedSource.objects.filter(pk=self.real_as.pk).exists())
        self.assertEqual(self.real_sol.lines.count(), 1)

    def test_seed_clear_roundtrip_restores_exact_counts(self):
        counts = lambda: {  # noqa: E731
            M.__name__: M.objects.count()
            for M in (Solicitation, SolicitationLine, DibbsAward,
                      ApprovedSource, ImportBatch, Supplier, Nsn)
        }
        before = counts()

        _seed()
        _seed(clear=True)

        self.assertEqual(counts(), before)

    def test_seeder_never_modifies_a_preexisting_nsn(self):
        # A real contracts_nsn row shared with contracts/processing must not be
        # overwritten -- and must therefore never become deletable.
        existing = Nsn.objects.create(
            nsn_code='8465-01-613-1241',  # one the seeder wants to create
            description='REAL CARABINER RECORD',
            dimension_source_notes='measured on the bench',
        )

        _seed()

        existing.refresh_from_db()
        self.assertEqual(existing.description, 'REAL CARABINER RECORD')
        self.assertEqual(existing.dimension_source_notes, 'measured on the bench')

        _seed(clear=True)
        self.assertTrue(Nsn.objects.filter(pk=existing.pk).exists())
