"""Open SOLs tab, status deep links, and multi-status work-the-list."""
from django.urls import reverse

from quote.models import QuoteSolicitation
from quote.tests.test_phase1 import Phase1Base
from quote.views.solicitations import parse_queue_params


class QueueParamTests(Phase1Base):
    def test_parse_queue_params(self):
        self.assertEqual(parse_queue_params(None, None), {'tab': 'OPEN', 'statuses': ['MATCHED']})
        self.assertEqual(parse_queue_params('', ''), {'tab': 'OPEN', 'statuses': ['MATCHED']})
        self.assertEqual(parse_queue_params('OPEN', None), {'tab': 'OPEN', 'statuses': ['MATCHED']})
        self.assertEqual(
            parse_queue_params('open', 'matched,unmatched'),
            {'tab': 'OPEN', 'statuses': ['MATCHED', 'UNMATCHED']},
        )
        self.assertEqual(parse_queue_params('OPEN', 'any'), {'tab': 'OPEN', 'statuses': []})
        self.assertEqual(parse_queue_params('OPEN', 'NOPE'), {'tab': 'OPEN', 'statuses': ['MATCHED']})
        self.assertEqual(
            parse_queue_params('UNMATCHED', 'MATCHED'),
            {'tab': 'OPEN', 'statuses': ['UNMATCHED']},
        )
        self.assertEqual(parse_queue_params('MATCHED', None), {'tab': 'OPEN', 'statuses': ['MATCHED']})
        self.assertEqual(parse_queue_params('RFQ_SENT', 'UNMATCHED'), {'tab': 'RFQ_SENT', 'statuses': []})
        self.assertEqual(parse_queue_params('NOPE', None), {'tab': 'OPEN', 'statuses': ['MATCHED']})

    def test_queue_page_renders_the_new_contract(self):
        url = reverse('quote:solicitation_queue')
        page = self.client.get(url)
        self.assertContains(page, 'Open SOLs')
        self.assertContains(page, 'quote-filter-rail')
        self.assertContains(page, 'Show 3 more')
        self.assertContains(page, '"tab": "OPEN"')
        self.assertContains(page, '"statuses": ["MATCHED"]')
        legacy = self.client.get(url + '?tab=UNMATCHED&status=MATCHED')
        self.assertContains(legacy, '"statuses": ["UNMATCHED"]')
        rfq = self.client.get(url + '?tab=RFQ_SENT')
        self.assertContains(rfq, '"tab": "RFQ_SENT"')


class WalkStatusTests(Phase1Base):
    def _post(self, payload):
        return self.client.post(
            reverse('quote:walk_next'),
            data=payload,
            content_type='application/json',
        )

    def _move(self, sol, status):
        state = QuoteSolicitation.objects.get(solicitation=sol)
        state.set_status(status)
        state.save()
        return state

    def test_multi_status_run_claims_a_sol_that_became_matched(self):
        self._move(self.other_sol, 'MATCHED')
        res = self._post({
            'candidates': [self.other_sol.solicitation_number],
            'statuses': ['UNMATCHED', 'MATCHED'],
        }).json()
        self.assertEqual(res['sol'], self.other_sol.solicitation_number)

    def test_multi_status_run_skips_rfq_sent(self):
        self._move(self.other_sol, 'RFQ_SENT')
        res = self._post({
            'candidates': [self.other_sol.solicitation_number],
            'statuses': ['UNMATCHED', 'MATCHED'],
        }).json()
        self.assertIsNone(res['sol'])
        self.assertIn('RFQ', res['skipped'][0]['reason'])

    def test_legacy_status_still_filters(self):
        self._move(self.other_sol, 'MATCHED')
        res = self._post({
            'candidates': [self.other_sol.solicitation_number],
            'status': 'UNMATCHED',
        }).json()
        self.assertIsNone(res['sol'])

    def test_unknown_status_is_rejected(self):
        res = self._post({
            'candidates': [self.sol.solicitation_number],
            'statuses': ['NOPE'],
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error'], 'Unknown status.')

    def test_unknown_token_is_dropped_when_a_real_one_remains(self):
        self._move(self.other_sol, 'MATCHED')
        res = self._post({
            'candidates': [self.other_sol.solicitation_number],
            'statuses': ['MATCHED', 'NOPE'],
        }).json()
        self.assertEqual(res['sol'], self.other_sol.solicitation_number)

    def test_missing_status_does_not_filter(self):
        self._move(self.other_sol, 'NO_BID')
        res = self._post({'candidates': [self.other_sol.solicitation_number]}).json()
        self.assertEqual(res['sol'], self.other_sol.solicitation_number)
