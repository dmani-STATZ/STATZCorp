"""Phase 1: queue dataset, workspace, manual matching + learning, RFQ dispatch, archival."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dibbs.models import ImportBatch, NsnProcurementHistory, Solicitation, SolicitationLine
from quote.models import (
    QuoteRFQ,
    QuoteSolicitation,
    QuoteSolicitationMatch,
    QuoteSupplierFSC,
    QuoteSupplierNSN,
)
from quote.services.archival import archive_stale_solicitations
from quote.services.matching import seed_solicitation_states
from quote.services.queue import build_queue_rows
from quote.services.rfq import compose_message, resolve_recipients
from suppliers.models import Contact, Supplier, SupplierContactCategory


class Phase1Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('rep', 'rep@example.com', 'x', first_name='Dion')
        self.other = User.objects.create_user('rep2', first_name='Barb')
        self.client.force_login(self.user)
        self.today = timezone.now().date()
        self.batch = ImportBatch.objects.create(import_date=self.today, imported_at=timezone.now())
        self.sol = self._sol('SPE1C126Q0528', '8465-01-613-1241', qty=10)
        self.other_sol = self._sol('SPE1C126Q0529', '8465-01-613-1241', qty=5)
        seed_solicitation_states([self.sol.pk, self.other_sol.pk])
        self.supplier = Supplier.objects.create(
            name='Vortex Tactical', cage_code='0SKY9', business_email='sales@vortex.example',
        )

    def _sol(self, number, nsn, qty, days=10):
        sol = Solicitation.objects.create(
            solicitation_number=number, return_by_date=self.today + timedelta(days=days),
            small_business_set_aside='R', import_batch=self.batch,
        )
        SolicitationLine.objects.create(
            solicitation=sol, nsn=nsn, fsc=nsn[:4], quantity=qty, unit_of_issue='EA',
            line_number='0001', nomenclature='CARABINER',
        )
        return sol

    def _status(self, sol):
        return QuoteSolicitation.objects.get(solicitation=sol).status

    def _url(self, name, sol=None, *args):
        sol = sol or self.sol
        return reverse(name, args=[sol.solicitation_number, *args])


class QueueTests(Phase1Base):
    def test_rows_carry_estimate_badges_and_status(self):
        NsnProcurementHistory.objects.create(
            nsn='8465016131241', fsc='8465', cage_code='0SKY9', contract_number='SPE1-OLD',
            quantity=Decimal('4'), unit_cost=Decimal('30.00000'),
            award_date=self.today - timedelta(days=400),
        )
        NsnProcurementHistory.objects.create(
            nsn='8465016131241', fsc='8465', cage_code='0SKY9', contract_number='SPE1-NEW',
            quantity=Decimal('4'), unit_cost=Decimal('32.50000'),
            award_date=self.today - timedelta(days=30),
        )
        QuoteSolicitationMatch.objects.create(
            solicitation=self.sol, supplier=self.supplier, source='MANUAL',
        )
        rows = {r['sol']: r for r in build_queue_rows()}
        row = rows['SPE1C126Q0528']
        self.assertEqual(row['estValue'], 325.0)  # latest unit cost x qty
        self.assertEqual(row['matches']['MANUAL'], 1)
        self.assertEqual(row['status'], 'UNMATCHED')
        self.assertEqual(row['nsn'], '8465-01-613-1241')

    def test_past_due_solicitations_are_excluded(self):
        late = self._sol('SPE1C126Q0001', '5999-01-333-4444', qty=1, days=-1)
        seed_solicitation_states([late.pk])
        self.assertNotIn('SPE1C126Q0001', {r['sol'] for r in build_queue_rows()})

    def test_pages_and_json_render(self):
        self.assertEqual(self.client.get(reverse('quote:solicitation_queue')).status_code, 200)
        data = self.client.get(reverse('quote:queue_data')).json()
        self.assertEqual(len(data['rows']), 2)
        self.assertEqual(len(data['rows'][0]), len(data['cols']))
        poll = self.client.get(reverse('quote:queue_poll'), {'since': data['now']}).json()
        self.assertEqual(poll['changed'], [])
        self.assertEqual(self.client.get(reverse('quote:rfq_queue')).status_code, 200)
        self.assertEqual(self.client.get(reverse('quote:dashboard')).status_code, 200)


class WorkspaceTests(Phase1Base):
    def test_opening_claims_and_poll_reports_it(self):
        since = timezone.now().isoformat()
        self.assertEqual(self.client.get(self._url('quote:solicitation_workspace')).status_code, 200)
        state = QuoteSolicitation.objects.get(solicitation=self.sol)
        self.assertEqual(state.claimed_by, self.user)
        poll = self.client.get(reverse('quote:queue_poll'), {'since': since}).json()
        self.assertIn(str(self.sol.pk), poll['claims'])

    def test_another_reps_claim_is_respected(self):
        state = QuoteSolicitation.objects.get(solicitation=self.sol)
        state.claim_for(self.other)
        resp = self.client.get(self._url('quote:solicitation_workspace'))
        self.assertContains(resp, 'is reviewing this solicitation')
        state.refresh_from_db()
        self.assertEqual(state.claimed_by, self.other)

    def test_manual_match_learns_nsn_and_matches_siblings(self):
        self.client.post(self._url('quote:add_match'), {
            'supplier_id': self.supplier.pk, 'save_nsn': 'on',
        })
        self.assertEqual(self._status(self.sol), 'MATCHED')
        self.assertTrue(QuoteSupplierNSN.objects.filter(supplier=self.supplier, nsn='8465016131241').exists())
        self.assertFalse(QuoteSupplierFSC.objects.exists())
        # The other open solicitation on the same NSN matched automatically.
        self.assertEqual(self._status(self.other_sol), 'MATCHED')
        self.assertTrue(QuoteSolicitationMatch.objects.filter(
            solicitation=self.other_sol, supplier=self.supplier, source='NSN',
        ).exists())

    def test_removing_last_manual_match_reverts_to_unmatched(self):
        self.client.post(self._url('quote:add_match'), {'supplier_id': self.supplier.pk})
        self.client.post(self._url('quote:remove_match', None, self.supplier.pk))
        self.assertEqual(self._status(self.sol), 'UNMATCHED')

    def test_no_bid_and_reopen(self):
        self.client.post(self._url('quote:set_status'), {'action': 'no_bid'})
        self.assertEqual(self._status(self.sol), 'NO_BID')
        self.client.post(self._url('quote:set_status'), {'action': 'reopen'})
        self.assertEqual(self._status(self.sol), 'UNMATCHED')

    def test_supplier_search(self):
        results = self.client.get(reverse('quote:supplier_search'), {'q': '0sky9'}).json()['results']
        self.assertEqual([r['id'] for r in results], [self.supplier.pk])


class RFQTests(Phase1Base):
    def _queue(self):
        self.client.post(self._url('quote:add_match'), {'supplier_id': self.supplier.pk})
        self.client.post(self._url('quote:queue_supplier_rfqs'), {'supplier_ids': [self.supplier.pk]})

    def test_queue_is_idempotent(self):
        self._queue()
        self._queue()
        self.assertEqual(QuoteRFQ.objects.filter(supplier=self.supplier).count(), 1)

    def test_message_puts_sol_in_subject_and_body(self):
        self._queue()
        subject, body = compose_message(self.supplier, QuoteRFQ.objects.all(), self.user)
        self.assertIn('SPE1C126Q0528', subject)
        self.assertIn('SOL: SPE1C126Q0528', body)

    def test_sales_contacts_win_over_supplier_emails(self):
        sales, _ = SupplierContactCategory.objects.get_or_create(name='Sales')
        contact = Contact.objects.create(name='Pat', email='pat@vortex.example', supplier=self.supplier)
        contact.categories.add(sales)
        self.assertEqual(resolve_recipients(self.supplier), ['pat@vortex.example'])

    @patch('quote.services.rfq.send_mail_via_graph', return_value=True)
    def test_send_marks_sent_and_moves_solicitation(self, send):
        self._queue()
        self.client.post(reverse('quote:rfq_send', args=[self.supplier.pk]))
        rfq = QuoteRFQ.objects.get()
        self.assertEqual(rfq.status, 'SENT')
        self.assertEqual(rfq.email_sent_to, 'sales@vortex.example')
        self.assertEqual(self._status(self.sol), 'RFQ_SENT')
        self.assertEqual(send.call_args.kwargs['to_address'], 'sales@vortex.example')

    @patch('quote.services.rfq.send_mail_via_graph', return_value=False)
    def test_failed_send_changes_nothing_but_the_error(self, send):
        self._queue()
        self.client.post(reverse('quote:rfq_send', args=[self.supplier.pk]))
        rfq = QuoteRFQ.objects.get()
        self.assertEqual(rfq.status, 'QUEUED')
        self.assertEqual(rfq.send_attempts, 1)
        self.assertTrue(rfq.last_send_error)
        self.assertEqual(self._status(self.sol), 'MATCHED')

    def test_queue_page_handles_rfq_sent_without_user(self):
        self._queue()
        QuoteRFQ.objects.update(status='SENT', sent_at=timezone.now(), sent_by=None)
        self.assertEqual(self.client.get(reverse('quote:rfq_queue')).status_code, 200)

    def test_remove_only_unsent(self):
        self._queue()
        rfq = QuoteRFQ.objects.get()
        self.client.post(reverse('quote:rfq_remove', args=[rfq.pk]), {'next': 'https://evil.example/'})
        self.assertFalse(QuoteRFQ.objects.exists())


class ArchivalTests(Phase1Base):
    def test_stale_unmatched_and_expired_are_archived(self):
        QuoteSolicitation.objects.filter(solicitation=self.sol).update(
            status_changed_at=timezone.now() - timedelta(days=8),
        )
        expired = self._sol('SPE1C126Q0002', '5999-01-333-4444', qty=1, days=-2)
        seed_solicitation_states([expired.pk])
        QuoteSolicitation.objects.filter(solicitation=expired).update(status='MATCHED')

        result = archive_stale_solicitations()

        self.assertEqual(result, {'stale_unmatched': 1, 'expired': 1})
        self.assertEqual(self._status(self.sol), 'ARCHIVED')
        self.assertEqual(self._status(expired), 'ARCHIVED')
        self.assertEqual(self._status(self.other_sol), 'UNMATCHED')


class WalkTheListTests(Phase1Base):
    """Next-available navigation: skip teammates' SOLs and already-worked ones."""

    def setUp(self):
        super().setUp()
        self.third = self._sol('SPE1C126Q0530', '5999-01-333-4444', qty=1)
        self.fourth = self._sol('SPE1C126Q0531', '5999-01-333-4445', qty=1)
        seed_solicitation_states([self.third.pk, self.fourth.pk])
        self.list = [s.solicitation_number for s in (self.sol, self.other_sol, self.third, self.fourth)]

    def _next(self, candidates, release=None, status='UNMATCHED'):
        return self.client.post(
            reverse('quote:walk_next'),
            data={'candidates': candidates, 'status': status, 'release': release},
            content_type='application/json',
        ).json()

    def _state(self, sol):
        return QuoteSolicitation.objects.get(solicitation=sol)

    def test_skips_teammate_and_worked_solicitations(self):
        self._state(self.other_sol).claim_for(self.other)
        third = self._state(self.third)
        third.set_status('NO_BID')
        third.save()

        res = self._next(self.list[1:], release=self.list[0])

        self.assertEqual(res['sol'], 'SPE1C126Q0531')
        self.assertEqual(res['url'], reverse('quote:solicitation_workspace', args=['SPE1C126Q0531']))
        reasons = {s['sol']: s['reason'] for s in res['skipped']}
        self.assertIn('Barb is working it', reasons['SPE1C126Q0529'])
        self.assertIn('No bid', reasons['SPE1C126Q0530'])
        self.assertEqual(self._state(self.fourth).claimed_by, self.user)

    def test_moving_on_releases_the_previous_claim(self):
        self._state(self.sol).claim_for(self.user)
        self._next(self.list[1:], release=self.list[0])
        self.assertIsNone(self._state(self.sol).claimed_by)

    def test_end_of_list(self):
        # One claim per rep, so three teammates each hold one.
        for i, sol in enumerate((self.other_sol, self.third, self.fourth)):
            self._state(sol).claim_for(User.objects.create_user(f'teammate{i}'))
        res = self._next(self.list[1:])
        self.assertIsNone(res['sol'])
        self.assertEqual(len(res['skipped']), 3)

    def test_try_claim_is_exclusive_until_expiry(self):
        state = self._state(self.sol)
        self.assertTrue(state.try_claim(self.other))
        self.assertFalse(state.try_claim(self.user))
        QuoteSolicitation.objects.filter(pk=state.pk).update(
            claim_expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertTrue(state.try_claim(self.user))

    def test_heartbeat_reports_takeover(self):
        self.client.get(self._url('quote:solicitation_workspace'))
        self._state(self.sol).claim_for(self.other)  # Barb takes over
        res = self.client.post(self._url('quote:claim'), {'action': 'renew'}).json()
        self.assertFalse(res['held'])
        self.assertEqual(res['by'], 'Barb')

    def test_then_next_actions_answer_json(self):
        res = self.client.post(
            self._url('quote:set_status'), {'action': 'no_bid'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(res.json(), {'ok': True})
        self.assertEqual(self._status(self.sol), 'NO_BID')
