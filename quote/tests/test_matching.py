"""
Quote-side reaction to a DIBBS import: workflow state seeding and additive
NSN / FSC supplier matching, driven by dibbs.signals.import_completed.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from dibbs.models import ImportBatch, Solicitation, SolicitationLine
from dibbs.signals import send_import_completed
from quote.models import (
    QuoteRFQ,
    QuoteSolicitation,
    QuoteSolicitationMatch,
    QuoteSupplierFSC,
    QuoteSupplierNSN,
)
from quote.services.matching import match_solicitations, normalize_nsn
from suppliers.models import Supplier


class MatchingTests(TestCase):
    def setUp(self):
        today = timezone.now().date()
        self.batch = ImportBatch.objects.create(
            import_date=today, imported_at=timezone.now(), imported_by='test',
        )
        self.open_sol = self._sol('SPE1C126Q0001', today + timedelta(days=10), '8465-01-613-1241')
        self.fsc_sol = self._sol('SPE1C126Q0002', today + timedelta(days=10), '8465-01-000-0001')
        self.lonely_sol = self._sol('SPE1C126Q0003', today + timedelta(days=10), '5999-01-333-4444')
        self.expired_sol = self._sol('SPE1C126Q0004', today - timedelta(days=1), '5999-01-333-4445')

        self.nsn_supplier = Supplier.objects.create(name='NSN Supplier', cage_code='0SKY9')
        self.fsc_supplier = Supplier.objects.create(name='FSC Supplier', cage_code='72914')
        QuoteSupplierNSN.objects.create(supplier=self.nsn_supplier, nsn='8465016131241')
        QuoteSupplierFSC.objects.create(supplier=self.fsc_supplier, fsc='8465')

    def _sol(self, number, due, nsn):
        sol = Solicitation.objects.create(
            solicitation_number=number, return_by_date=due, import_batch=self.batch,
        )
        digits = nsn.replace('-', '')
        SolicitationLine.objects.create(
            solicitation=sol, nsn=nsn, fsc=digits[:4], line_number='0001',
        )
        return sol

    def _status(self, sol):
        return QuoteSolicitation.objects.get(solicitation=sol).status

    def test_import_signal_seeds_state_and_matches(self):
        send_import_completed(self.batch)

        self.assertEqual(self._status(self.open_sol), QuoteSolicitation.STATUS_MATCHED)
        self.assertEqual(self._status(self.fsc_sol), QuoteSolicitation.STATUS_MATCHED)
        self.assertEqual(self._status(self.lonely_sol), QuoteSolicitation.STATUS_UNMATCHED)
        self.assertEqual(self._status(self.expired_sol), QuoteSolicitation.STATUS_ARCHIVED)

    def test_matching_is_additive_with_lineage(self):
        send_import_completed(self.batch)

        sources = set(
            QuoteSolicitationMatch.objects.filter(solicitation=self.open_sol)
            .values_list('supplier__name', 'source')
        )
        # Same NSN hits the NSN supplier directly and the FSC supplier by class.
        self.assertEqual(sources, {
            ('NSN Supplier', QuoteSolicitationMatch.SOURCE_NSN),
            ('FSC Supplier', QuoteSolicitationMatch.SOURCE_FSC),
        })

    def test_rerun_is_idempotent_and_keeps_manual_matches(self):
        send_import_completed(self.batch)
        manual = Supplier.objects.create(name='Manual Pick', cage_code='1ALL7')
        QuoteSolicitationMatch.objects.create(
            solicitation=self.lonely_sol, supplier=manual,
            source=QuoteSolicitationMatch.SOURCE_MANUAL,
        )
        before = QuoteSolicitationMatch.objects.count()

        send_import_completed(self.batch)

        self.assertEqual(QuoteSolicitationMatch.objects.count(), before)
        self.assertTrue(
            QuoteSolicitationMatch.objects.filter(
                solicitation=self.lonely_sol, source=QuoteSolicitationMatch.SOURCE_MANUAL,
            ).exists()
        )

    def test_matching_never_rewinds_a_worked_solicitation(self):
        send_import_completed(self.batch)
        state = QuoteSolicitation.objects.get(solicitation=self.lonely_sol)
        state.set_status(QuoteSolicitation.STATUS_RFQ_SENT)
        state.save()
        QuoteSupplierNSN.objects.create(supplier=self.nsn_supplier, nsn='5999013334444')

        match_solicitations([self.lonely_sol.pk])

        self.assertEqual(self._status(self.lonely_sol), QuoteSolicitation.STATUS_RFQ_SENT)

    def test_failing_receiver_never_breaks_the_import(self):
        from dibbs.signals import import_completed

        def boom(**kwargs):
            raise RuntimeError('downstream bug')

        import_completed.connect(boom, dispatch_uid='test.boom')
        try:
            responses = send_import_completed(self.batch)
        finally:
            import_completed.disconnect(dispatch_uid='test.boom')

        self.assertTrue(any(isinstance(r, RuntimeError) for _, r in responses))
        # The quote receiver still ran.
        self.assertTrue(QuoteSolicitation.objects.filter(solicitation=self.open_sol).exists())

    def test_normalize_nsn(self):
        self.assertEqual(normalize_nsn('8465-01-613-1241'), '8465016131241')
        self.assertEqual(normalize_nsn('8465 01 613'), '')
        self.assertEqual(normalize_nsn(None), '')


class BatchDeleteProtectionTests(TestCase):
    """Deleting an import batch must never cascade into quote workflow rows."""

    def test_worked_solicitations_survive_batch_delete(self):
        from django.contrib.auth.models import User
        from django.urls import reverse

        batch = ImportBatch.objects.create(
            import_date=timezone.now().date(), imported_at=timezone.now(),
        )
        worked = Solicitation.objects.create(solicitation_number='SPE1C126Q0100', import_batch=batch)
        worked_line = SolicitationLine.objects.create(solicitation=worked, nsn='8465016131241')
        untouched = Solicitation.objects.create(solicitation_number='SPE1C126Q0101', import_batch=batch)
        SolicitationLine.objects.create(solicitation=untouched, nsn='8465016131242')
        supplier = Supplier.objects.create(name='Vortex', cage_code='0SKY9')
        QuoteRFQ.objects.create(line=worked_line, supplier=supplier)

        user = User.objects.create_superuser('admin', 'a@example.com', 'x')
        self.client.force_login(user)
        self.client.post(reverse('dibbs:import_batch_delete', args=[batch.pk]))

        self.assertTrue(Solicitation.objects.filter(pk=worked.pk).exists())
        self.assertTrue(QuoteRFQ.objects.filter(line=worked_line).exists())
        self.assertFalse(Solicitation.objects.filter(pk=untouched.pk).exists())
