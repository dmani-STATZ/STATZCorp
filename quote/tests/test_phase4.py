"""Phase 4: award reconciliation, derived pricing, trends, Our Bids views."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dibbs.models import DibbsAward, SolicitationLine
from quote.models import BidOutcome
from quote.services import bids, outcomes
from quote.tasks.reconcile_bid_outcomes import reconcile_bid_outcomes_task
from quote.tests.test_phase3 import Phase3Base


class Phase4Base(Phase3Base):
    def setUp(self):
        super().setUp()
        self.line.purchase_request_number = '7018302110'
        self.line.save()
        bid = self._ready_bid()
        bids.export_bids([bid.pk], self.user)
        self.outcome = BidOutcome.objects.get(bid=bid)
        self.n = 0

    def award(self, cage, total=None, faux=False, pr='7018302110', nsn='8465016131241', days_ago=1):
        self.n += 1
        return DibbsAward.objects.create(
            sol_number='SPE1C126Q0528', notice_id=f'TEST-{self.n}',
            award_date=timezone.now().date() - timedelta(days=days_ago),
            awardee_cage=cage, total_contract_price=total, is_faux=faux,
            purchase_request=pr, nsn=nsn, award_basic_number=f'SPE1C126P{self.n:04d}',
        )

    def reload(self):
        self.outcome.refresh_from_db()
        return self.outcome


class ReconcileTests(Phase4Base):
    def test_pending_until_an_award_posts(self):
        self.assertEqual(outcomes.reconcile()['still_pending'], 1)
        self.assertEqual(self.reload().outcome, 'PENDING')

    def test_we_won(self):
        price = self.outcome.our_unit_price
        self.award('3WGD1', total=price * 2)
        outcomes.reconcile()
        o = self.reload()
        self.assertEqual(o.outcome, 'WON')
        self.assertEqual(o.award_unit_price, price)          # total / qty 2
        self.assertEqual(o.dollar_delta, Decimal('0'))
        self.assertTrue(o.award_unit_price_is_derived)

    def test_lost_within_five_percent(self):
        our = self.outcome.our_unit_price
        winning = (our / Decimal('1.03')).quantize(Decimal('0.01'))
        self.award('D2689', total=winning * 2)
        outcomes.reconcile()
        o = self.reload()
        self.assertEqual(o.outcome, 'LOST')
        self.assertEqual(o.winning_cage, 'D2689')
        self.assertTrue(o.within_5_pct)
        self.assertGreater(o.pct_spread, 0)

    def test_faux_award_then_real_award_upgrades(self):
        self.award('D2689', faux=True)
        outcomes.reconcile()
        o = self.reload()
        self.assertEqual(o.outcome, 'LOST')
        self.assertIsNone(o.award_unit_price)
        self.award('D2689', total=Decimal('50.00'))
        outcomes.reconcile()                                  # faux outcomes are re-checked
        o = self.reload()
        self.assertFalse(o.award.is_faux)
        self.assertEqual(o.award_unit_price, Decimal('25.00000'))

    def test_line_matching_prefers_purchase_request(self):
        SolicitationLine.objects.create(
            solicitation=self.sol, nsn='8465-01-613-1241', quantity=5, line_number='0002',
            purchase_request_number='9999999999',
        )
        self.award('ZZZZZ', total=Decimal('10'), pr='9999999999')   # the other line's award
        outcomes.reconcile()
        self.assertEqual(self.reload().outcome, 'PENDING')
        self.award('3WGD1', total=Decimal('70'))
        outcomes.reconcile()
        self.assertEqual(self.reload().outcome, 'WON')

    def test_task_never_raises(self):
        reconcile_bid_outcomes_task()


class TrendsAndViewsTests(Phase4Base):
    def test_trends_what_if(self):
        self.award('D2689', total=Decimal('20.00'))    # $10/unit: far under our landed cost
        outcomes.reconcile()
        notes = ' '.join(outcomes.trends(self.reload()))
        self.assertIn('no markup would have won', notes)

    def test_rows_and_pages(self):
        self.award('D2689', total=Decimal('60.00'))
        outcomes.reconcile()
        row = outcomes.rows()[0]
        self.assertEqual((row['status'], row['sol']), ('LOST', 'SPE1C126Q0528'))

        self.assertEqual(self.client.get(reverse('quote:our_bids')).status_code, 200)
        resp = self.client.get(reverse('quote:outcome_detail', args=[self.outcome.pk]),
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(resp, 'Frozen bid snapshot')
        self.assertContains(resp, 'Vortex Tactical')
        self.assertRedirects(self.client.post(reverse('quote:reconcile_now')), reverse('quote:our_bids'))
