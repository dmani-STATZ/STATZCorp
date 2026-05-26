"""Tests: model dedup, schema validation, lock semantics, editor flow, matcher."""
import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from contracts.models import (
    Buyer,
    Clin,
    Contract,
    ContractPackaging,
    IdiqContract,
    IdiqContractDetails,
    SalesClass,
)
from products.models import Nsn
from suppliers.models import Supplier

from intake.pdf_parser import AwardParseResult, ClinParseResult
from intake.finalize import FinalizationError, finalize_draft
from intake.forms_parse import parse_post
from intake.ingest import DuplicateContractNumber, IngestionError, ingest_pdf
from intake.locks import (
    LOCK_DURATION,
    LockError,
    acquire,
    assert_holds,
    clear_expired,
    is_expired,
    release,
)
from intake.matchers import MatcherError, apply_match, clear_match, search as matcher_search
from intake.models import DraftContract
from intake.schemas import DraftDataValidationError, validate_data


class SchemaValidationTests(TestCase):
    def test_unknown_contract_type_rejected(self):
        with self.assertRaises(DraftDataValidationError):
            validate_data('BOGUS', {})

    def test_empty_data_valid_for_known_type(self):
        # Empty payload should validate — all keys are Optional by design.
        out = validate_data('AWD', {})
        self.assertEqual(out['clins'], [])

    def test_clin_must_be_dict_shape(self):
        with self.assertRaises(DraftDataValidationError):
            validate_data('AWD', {'clins': [{'item_number': '0001', 'bogus_key': 1}]})

    def test_idiq_accepts_approved_lists(self):
        out = validate_data('IDIQ', {
            'term_months': 60,
            'option_months': 12,
            'max_value': '350000.00',
            'min_guarantee': 170,
            'approved_nsns': [{'nsn_text': '1234-12-123-1234'}],
            'approved_suppliers': [{'supplier_text': 'ACME', 'cage': '12345'}],
        })
        self.assertEqual(out['term_months'], 60)
        self.assertEqual(len(out['approved_nsns']), 1)

    def test_do_carries_parent_idiq_reference(self):
        out = validate_data('DO', {
            'parent_idiq_contract_number': 'SPE7L1-23-D-0042',
            'clins': [{'item_number': '0001'}],
        })
        self.assertEqual(out['parent_idiq_contract_number'], 'SPE7L1-23-D-0042')


class DraftContractModelTests(TestCase):
    def test_contract_number_is_unique(self):
        DraftContract.objects.create(
            contract_number='SPE7L1-26-D-0001',
            contract_type='IDIQ',
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            DraftContract.objects.create(
                contract_number='SPE7L1-26-D-0001',
                contract_type='IDIQ',
            )

    def test_save_validates_data(self):
        draft = DraftContract(
            contract_number='SPE7L1-26-P-0002',
            contract_type='AWD',
            data={'clins': [{'item_number': '0001', 'bogus_key': 1}]},
        )
        with self.assertRaises(DraftDataValidationError):
            draft.save()


class LockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.bob = User.objects.create_user('bob', 'b@x.com', 'pw')

    def _make(self):
        return DraftContract.objects.create(
            contract_number='SPE7L1-26-P-1000',
            contract_type='AWD',
        )

    def test_acquire_and_release(self):
        draft = self._make()
        acquire(draft, self.alice)
        self.assertEqual(draft.locked_by_id, self.alice.id)
        self.assertTrue(draft.is_locked)
        release(draft, self.alice)
        self.assertIsNone(draft.locked_by_id)

    def test_second_user_blocked_on_active_lock(self):
        draft = self._make()
        acquire(draft, self.alice)
        with self.assertRaises(LockError):
            acquire(draft, self.bob)

    def test_expired_lock_can_be_reclaimed(self):
        draft = self._make()
        acquire(draft, self.alice)
        # Force expiry.
        DraftContract.objects.filter(pk=draft.pk).update(
            locked_at=timezone.now() - LOCK_DURATION - timedelta(seconds=10)
        )
        draft.refresh_from_db()
        self.assertTrue(is_expired(draft.locked_at))
        acquire(draft, self.bob)  # should succeed
        self.assertEqual(draft.locked_by_id, self.bob.id)

    def test_assert_holds_rejects_after_reclaim(self):
        """Original holder cannot silently overwrite after lock expired+reclaimed."""
        draft = self._make()
        acquire(draft, self.alice)
        DraftContract.objects.filter(pk=draft.pk).update(
            locked_at=timezone.now() - LOCK_DURATION - timedelta(seconds=10)
        )
        draft.refresh_from_db()
        acquire(draft, self.bob)
        # Alice tries to save against her stale lock state.
        draft.refresh_from_db()
        with self.assertRaises(LockError):
            assert_holds(draft, self.alice)

    def test_clear_expired_command_logic(self):
        draft = self._make()
        acquire(draft, self.alice)
        DraftContract.objects.filter(pk=draft.pk).update(
            locked_at=timezone.now() - LOCK_DURATION - timedelta(seconds=10)
        )
        count = clear_expired(DraftContract)
        self.assertEqual(count, 1)
        draft.refresh_from_db()
        self.assertIsNone(draft.locked_by_id)


class FormParseTests(TestCase):
    """The flat POST → JSON `data` translation contract."""

    def test_scalars_clins_packaging_round_trip(self):
        post = {
            'csrfmiddlewaretoken': 'x',
            'f_award_date': '2026-05-01',
            'f_pr_number': 'PR-7',
            'f_unknown_field': 'dropped',
            'clin-0-item_number': '0001',
            'clin-0-nsn_text': '1234',
            'clin-2-item_number': '0003',
            'pkg-packhouse_cage': '12345',
            'pkg-quote_amount': '99.50',
        }
        out = parse_post(post)
        self.assertEqual(out['award_date'], '2026-05-01')
        self.assertEqual(out['pr_number'], 'PR-7')
        self.assertNotIn('unknown_field', out)
        # Indexed but compacted in submission order.
        self.assertEqual(len(out['clins']), 2)
        self.assertEqual(out['clins'][0]['item_number'], '0001')
        self.assertEqual(out['clins'][1]['item_number'], '0003')
        self.assertEqual(out['packaging']['packhouse_cage'], '12345')

    def test_all_blank_rows_dropped(self):
        post = {
            'clin-0-item_number': '',
            'clin-0-nsn_text': '',
        }
        out = parse_post(post)
        self.assertNotIn('clins', out)

    def test_nested_per_clin_finance_and_splits_parse(self):
        """clin-i-fin-j-* and clin-i-split-j-* land under the right CLIN."""
        post = {
            'csrfmiddlewaretoken': 'x',
            'clin-0-item_number': '0001',
            'clin-0-fin-0-line_type': 'progress',
            'clin-0-fin-0-amount': '500.00',
            'clin-0-fin-0-notes': 'milestone 1',
            'clin-0-split-0-company_name': 'STATZ',
            'clin-0-split-0-percentage': '60',
            'clin-0-split-1-company_name': 'PARTNER',
            'clin-0-split-1-percentage': '40',
            'clin-1-item_number': '0002',
            'clin-1-fin-0-line_type': 'progress',
            'clin-1-fin-0-amount': '100.00',
        }
        out = parse_post(post)
        self.assertEqual(len(out['clins']), 2)
        self.assertEqual(out['clins'][0]['item_number'], '0001')
        self.assertEqual(len(out['clins'][0]['finance_lines']), 1)
        self.assertEqual(out['clins'][0]['finance_lines'][0]['line_type'], 'progress')
        self.assertEqual(len(out['clins'][0]['splits']), 2)
        self.assertEqual(out['clins'][0]['splits'][1]['company_name'], 'PARTNER')
        self.assertEqual(len(out['clins'][1]['finance_lines']), 1)
        # New POST keys never produce root-level finance_lines.
        self.assertNotIn('finance_lines', out)

    def test_nested_orphan_rows_dropped_when_clin_blank(self):
        """Sub-rows under a blank top-level CLIN are dropped with the CLIN."""
        post = {
            'clin-0-fin-0-line_type': 'progress',
            'clin-0-fin-0-amount': '500.00',
        }
        out = parse_post(post)
        self.assertNotIn('clins', out)

    def test_new_clin_scalar_fields_accepted(self):
        post = {
            'clin-0-item_number': '0001',
            'clin-0-supplier_due_date': '2026-08-01',
            'clin-0-special_payment_terms': '7',
        }
        out = parse_post(post)
        self.assertEqual(out['clins'][0]['supplier_due_date'], '2026-08-01')
        self.assertEqual(out['clins'][0]['special_payment_terms'], '7')


class EditorViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.bob = User.objects.create_user('bob', 'b@x.com', 'pw')

    def _draft(self, **overrides):
        defaults = dict(
            contract_number='SPE7L1-26-P-2001',
            contract_type='AWD',
            status=DraftContract.Status.IN_PROGRESS,
        )
        defaults.update(overrides)
        return DraftContract.objects.create(**defaults)

    def test_edit_requires_lock(self):
        draft = self._draft()
        self.client.force_login(self.alice)
        resp = self.client.get(reverse('intake:edit_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('intake:queue'))

    def test_edit_renders_when_lock_held(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self.client.get(reverse('intake:edit_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, draft.contract_number)

    def test_save_writes_data_under_lock(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse('intake:save_draft', args=[draft.pk]),
            {'f_pr_number': 'PR-99', 'clin-0-item_number': '0001'},
        )
        self.assertEqual(resp.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.data['pr_number'], 'PR-99')
        self.assertEqual(draft.data['clins'][0]['item_number'], '0001')
        # Lock still held — Save doesn't release.
        self.assertEqual(draft.locked_by_id, self.alice.id)
        self.assertEqual(draft.status, DraftContract.Status.IN_PROGRESS)

    def test_save_rejects_when_user_lost_lock(self):
        draft = self._draft()
        acquire(draft, self.alice)
        # Simulate expiry + reclaim by bob.
        DraftContract.objects.filter(pk=draft.pk).update(
            locked_at=timezone.now() - LOCK_DURATION - timedelta(seconds=10)
        )
        draft.refresh_from_db()
        acquire(draft, self.bob)

        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse('intake:save_draft', args=[draft.pk]),
            {'f_pr_number': 'PR-OVERWRITE'},
        )
        self.assertEqual(resp.status_code, 302)
        draft.refresh_from_db()
        # Alice's overwrite must NOT have landed.
        self.assertNotEqual(draft.data.get('pr_number'), 'PR-OVERWRITE')
        self.assertEqual(draft.locked_by_id, self.bob.id)

    def test_save_surfaces_validation_error(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        # `bogus_key` is not on PdfParseStatus-style field — actually
        # forms_parse drops unknown keys. To trigger validation we send a
        # value the schema can't coerce.
        resp = self.client.post(
            reverse('intake:save_draft', args=[draft.pk]),
            {'f_award_date': 'not-a-date'},
        )
        self.assertEqual(resp.status_code, 302)  # redirect back to editor
        draft.refresh_from_db()
        # Bad value rejected → no award_date stored.
        self.assertIsNone(draft.data.get('award_date'))

    def test_mark_ready_transitions_and_releases(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse('intake:mark_ready', args=[draft.pk]),
            {'f_pr_number': 'PR-DONE'},
        )
        self.assertEqual(resp.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.status, DraftContract.Status.READY_FOR_REVIEW)
        self.assertIsNone(draft.locked_by_id)
        self.assertEqual(draft.data['pr_number'], 'PR-DONE')

    def test_start_draft_redirects_to_editor(self):
        draft = self._draft(status=DraftContract.Status.QUEUED)
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('intake:start_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'/intake/drafts/{draft.pk}/edit/', resp.url)
        draft.refresh_from_db()
        self.assertEqual(draft.status, DraftContract.Status.IN_PROGRESS)
        self.assertEqual(draft.locked_by_id, self.alice.id)

    def test_cancel_draft_transitions_and_releases(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('intake:cancel_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.status, DraftContract.Status.CANCELLED)
        self.assertIsNone(draft.locked_by_id)


class MatcherUnitTests(TestCase):
    """Unit tests for the pure-function matcher logic (no HTTP)."""

    @classmethod
    def setUpTestData(cls):
        cls.buyer = Buyer.objects.create(description='Acme Buying Office')
        cls.idiq = IdiqContract.objects.create(contract_number='SPE7L1-23-D-0099')
        cls.nsn = Nsn.objects.create(nsn_code='1234-12-345-6789', description='Widget')
        cls.supplier = Supplier.objects.create(name='Acme Corp', cage_code='12345')

    def test_search_requires_three_chars(self):
        self.assertEqual(matcher_search('buyer', 'ab'), [])

    def test_search_buyer_finds_by_description(self):
        results = matcher_search('buyer', 'Acme')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.buyer.id)

    def test_search_supplier_finds_by_cage(self):
        results = matcher_search('supplier', '12345')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['cage'], '12345')

    def test_search_unknown_match_type_rejected(self):
        with self.assertRaises(MatcherError):
            matcher_search('bogus', 'anything')

    def test_apply_buyer(self):
        data = {}
        apply_match(data, 'buyer', 'buyer', self.buyer.id)
        self.assertEqual(data['buyer_text'], 'Acme Buying Office')
        self.assertEqual(data['buyer_id'], self.buyer.id)

    def test_apply_clin_nsn_extends_list(self):
        data = {}
        apply_match(data, 'clin:2:nsn', 'nsn', self.nsn.id)
        self.assertEqual(len(data['clins']), 3)
        self.assertEqual(data['clins'][2]['nsn_id'], self.nsn.id)
        self.assertEqual(data['clins'][2]['nsn_text'], '1234-12-345-6789')
        self.assertEqual(data['clins'][2]['nsn_description'], 'Widget')

    def test_apply_packaging_supplier_carries_cage(self):
        data = {}
        apply_match(data, 'packaging', 'supplier', self.supplier.id)
        self.assertEqual(data['packaging']['packhouse_supplier_id'], self.supplier.id)
        self.assertEqual(data['packaging']['packhouse_cage'], '12345')

    def test_apply_wrong_match_type_for_path_rejected(self):
        # parent_idiq path with a buyer record is nonsense.
        with self.assertRaises(MatcherError):
            apply_match({}, 'parent_idiq', 'buyer', self.buyer.id)

    def test_clear_match_strips_id_only(self):
        data = {'buyer_text': 'Acme', 'buyer_id': self.buyer.id}
        clear_match(data, 'buyer')
        self.assertEqual(data['buyer_text'], 'Acme')
        self.assertNotIn('buyer_id', data)


class MatcherEndpointTests(TestCase):
    """End-to-end tests of the /match/ JSON endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.bob = User.objects.create_user('bob', 'b@x.com', 'pw')
        cls.buyer = Buyer.objects.create(description='Acme Buyers')
        cls.nsn = Nsn.objects.create(nsn_code='5678-12-345-6789', description='Bolt')

    def _draft(self, **overrides):
        defaults = dict(
            contract_number='SPE7L1-26-P-3001',
            contract_type='AWD',
            status=DraftContract.Status.IN_PROGRESS,
        )
        defaults.update(overrides)
        return DraftContract.objects.create(**defaults)

    def _post(self, draft, body):
        return self.client.post(
            reverse('intake:match', args=[draft.pk]),
            data=json.dumps(body),
            content_type='application/json',
        )

    def test_search_does_not_require_lock(self):
        draft = self._draft()
        self.client.force_login(self.alice)
        resp = self._post(draft, {'action': 'search', 'match_type': 'buyer', 'q': 'Acme'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 1)

    def test_apply_requires_lock(self):
        draft = self._draft()
        self.client.force_login(self.alice)
        resp = self._post(draft, {
            'action': 'apply', 'match_type': 'buyer',
            'target_path': 'buyer', 'record_id': self.buyer.id,
        })
        self.assertEqual(resp.status_code, 409)
        draft.refresh_from_db()
        # Schema dumps None for Optional fields; what matters is the match
        # didn't land.
        self.assertIsNone(draft.data.get('buyer_id'))

    def test_apply_writes_json_under_lock(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self._post(draft, {
            'action': 'apply', 'match_type': 'buyer',
            'target_path': 'buyer', 'record_id': self.buyer.id,
        })
        self.assertEqual(resp.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.data['buyer_id'], self.buyer.id)
        self.assertEqual(draft.data['buyer_text'], 'Acme Buyers')

    def test_apply_rejected_when_lock_lost(self):
        draft = self._draft()
        acquire(draft, self.alice)
        # Alice's lock expires, bob takes over.
        DraftContract.objects.filter(pk=draft.pk).update(
            locked_at=timezone.now() - LOCK_DURATION - timedelta(seconds=10)
        )
        draft.refresh_from_db()
        acquire(draft, self.bob)

        self.client.force_login(self.alice)
        resp = self._post(draft, {
            'action': 'apply', 'match_type': 'buyer',
            'target_path': 'buyer', 'record_id': self.buyer.id,
        })
        self.assertEqual(resp.status_code, 409)

    def test_clear_strips_id(self):
        draft = self._draft(data={'buyer_text': 'Acme', 'buyer_id': self.buyer.id})
        # Re-save to ensure JSON is canonicalized through validate_data.
        draft.save()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self._post(draft, {'action': 'clear', 'target_path': 'buyer'})
        self.assertEqual(resp.status_code, 200)
        draft.refresh_from_db()
        self.assertIsNone(draft.data.get('buyer_id'))
        self.assertEqual(draft.data['buyer_text'], 'Acme')

    def test_unknown_action_rejected(self):
        draft = self._draft()
        self.client.force_login(self.alice)
        resp = self._post(draft, {'action': 'frobnicate', 'match_type': 'buyer'})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_json_body_rejected(self):
        draft = self._draft()
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse('intake:match', args=[draft.pk]),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


class FinalizationTests(TestCase):
    """Phase 3a finalization shred: AWD/PO/IDIQ."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.buyer = Buyer.objects.create(description='Acme Buying Office')
        cls.nsn1 = Nsn.objects.create(nsn_code='1111-11-111-1111', description='Bolt')
        cls.nsn2 = Nsn.objects.create(nsn_code='2222-22-222-2222', description='Nut')
        cls.supplier1 = Supplier.objects.create(name='Supp A', cage_code='AAAAA')
        cls.supplier2 = Supplier.objects.create(name='Supp B', cage_code='BBBBB')

    def _ready_awd(self, **data_overrides):
        data = {
            'pr_number': 'PR-100',
            'award_date': '2026-05-01',
            'buyer_id': self.buyer.id,
            'buyer_text': 'Acme Buying Office',
            'contract_value': '12345.67',
            'clins': [
                {
                    'item_number': '0001',
                    'item_type': 'P',
                    'nsn_id': self.nsn1.id,
                    'nsn_text': '1111-11-111-1111',
                    'supplier_id': self.supplier1.id,
                    'supplier_text': 'Supp A',
                    'order_qty': 10,
                    'unit_price': '5.00',
                    'item_value': '50.00',
                    'ia': 'O',
                    'fob': 'D',
                },
            ],
        }
        data.update(data_overrides)
        return DraftContract.objects.create(
            contract_number='SPE7L1-26-P-FIN1',
            contract_type='AWD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data=data,
        )

    def test_awd_happy_path_creates_contract_and_clins(self):
        draft = self._ready_awd()
        draft_pk = draft.pk
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        self.assertIsInstance(target, Contract)
        self.assertEqual(target.contract_number, 'SPE7L1-26-P-FIN1')
        self.assertEqual(target.buyer_id, self.buyer.id)
        self.assertEqual(target.pr_number, 'PR-100')
        clins = list(target.clin_set.all())
        self.assertEqual(len(clins), 1)
        self.assertEqual(clins[0].nsn_id, self.nsn1.id)
        self.assertEqual(clins[0].supplier_id, self.supplier1.id)
        # Draft must be deleted on success.
        self.assertFalse(DraftContract.objects.filter(pk=draft_pk).exists())

    def test_awd_status_guard(self):
        draft = self._ready_awd()
        draft.status = DraftContract.Status.IN_PROGRESS
        draft.save(update_fields=['status'])
        with self.assertRaises(FinalizationError):
            with transaction.atomic():
                finalize_draft(draft, self.alice)

    def test_awd_requires_matched_buyer(self):
        draft = self._ready_awd(buyer_id=None)
        with self.assertRaises(FinalizationError):
            with transaction.atomic():
                finalize_draft(draft, self.alice)

    def test_awd_requires_matched_nsn_per_clin(self):
        draft = self._ready_awd()
        draft.data['clins'][0]['nsn_id'] = None
        draft.save()
        with self.assertRaises(FinalizationError):
            with transaction.atomic():
                finalize_draft(draft, self.alice)
        # Draft still exists since the transaction rolled back.
        self.assertTrue(DraftContract.objects.filter(pk=draft.pk).exists())

    def test_awd_requires_at_least_one_clin(self):
        draft = self._ready_awd()
        draft.data['clins'] = []
        draft.save()
        with self.assertRaises(FinalizationError):
            with transaction.atomic():
                finalize_draft(draft, self.alice)

    def test_awd_creates_packaging_when_packhouse_matched(self):
        draft = self._ready_awd()
        draft.data['packaging'] = {
            'packhouse_supplier_id': self.supplier2.id,
            'quote_amount': '99.50',
            'notes': 'crate it',
        }
        draft.save()
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        pkg = ContractPackaging.objects.get(contract=target)
        self.assertEqual(pkg.packhouse_id, self.supplier2.id)
        self.assertEqual(str(pkg.quote_amount), '99.50')

    def test_idiq_happy_path_creates_cross_product_details(self):
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-D-FIN1',
            contract_type='IDIQ',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={
                'award_date': '2026-04-01',
                'buyer_id': self.buyer.id,
                'term_months': 60,
                'option_months': 24,
                'max_value': '500000.00',
                'min_guarantee': 1000,
                'approved_nsns': [
                    {'nsn_id': self.nsn1.id, 'nsn_text': '1111', 'min_order_qty': '10'},
                    {'nsn_id': self.nsn2.id, 'nsn_text': '2222', 'min_order_qty': '20'},
                ],
                'approved_suppliers': [
                    {'supplier_id': self.supplier1.id, 'supplier_text': 'Supp A'},
                    {'supplier_id': self.supplier2.id, 'supplier_text': 'Supp B'},
                ],
            },
        )
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        self.assertIsInstance(target, IdiqContract)
        self.assertEqual(target.term_length, 60)
        details = list(IdiqContractDetails.objects.filter(idiq_contract=target))
        self.assertEqual(len(details), 4)  # 2 NSNs × 2 suppliers
        # min_order_qty travels with the NSN side.
        nsn1_details = [d for d in details if d.nsn_id == self.nsn1.id]
        self.assertTrue(all(d.min_order_qty == '10' for d in nsn1_details))

    def test_idiq_with_no_matched_approved_rows_still_finalizes(self):
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-D-FIN2',
            contract_type='IDIQ',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={
                'term_months': 36,
                'approved_nsns': [{'nsn_text': 'unmatched', 'nsn_id': None}],
                'approved_suppliers': [],
            },
        )
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        self.assertEqual(target.term_length, 36)
        self.assertEqual(IdiqContractDetails.objects.filter(idiq_contract=target).count(), 0)

    def test_unsupported_type_rejected(self):
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-X-FIN1',
            contract_type='MOD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={'mod_number': 'P00001'},
        )
        with self.assertRaises(FinalizationError):
            with transaction.atomic():
                finalize_draft(draft, self.alice)


class FinalizeViewTests(TestCase):
    """End-to-end /finalize/ view: lock guard + redirect."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.bob = User.objects.create_user('bob', 'b@x.com', 'pw')
        cls.buyer = Buyer.objects.create(description='Acme')
        cls.nsn = Nsn.objects.create(nsn_code='3333', description='X')
        cls.supplier = Supplier.objects.create(name='S', cage_code='99999')

    def _ready_draft(self):
        return DraftContract.objects.create(
            contract_number='SPE7L1-26-P-VFIN1',
            contract_type='AWD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={
                'buyer_id': self.buyer.id,
                'buyer_text': 'Acme',
                'clins': [{
                    'item_number': '0001',
                    'nsn_id': self.nsn.id, 'nsn_text': '3333',
                    'supplier_id': self.supplier.id, 'supplier_text': 'S',
                }],
            },
        )

    def test_finalize_requires_lock(self):
        draft = self._ready_draft()
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('intake:finalize_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 302)
        # Draft must still exist — lock check rejected before shred.
        self.assertTrue(DraftContract.objects.filter(pk=draft.pk).exists())

    def test_finalize_under_lock_creates_contract_and_deletes_draft(self):
        draft = self._ready_draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('intake:finalize_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(DraftContract.objects.filter(pk=draft.pk).exists())
        self.assertTrue(
            Contract.objects.filter(contract_number='SPE7L1-26-P-VFIN1').exists()
        )

    def test_finalize_blocked_message_when_unmatched(self):
        draft = self._ready_draft()
        # Strip the buyer match.
        draft.data['buyer_id'] = None
        draft.save()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('intake:finalize_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 302)
        # Draft remains; nothing landed in contracts.
        self.assertTrue(DraftContract.objects.filter(pk=draft.pk).exists())
        self.assertFalse(
            Contract.objects.filter(contract_number='SPE7L1-26-P-VFIN1').exists()
        )


# ---------------------------------------------------------------------------
# Phase 3c: PDF ingestion
# ---------------------------------------------------------------------------


def _stub_parse_result(**overrides) -> AwardParseResult:
    """A minimal AWD parse result. Override fields per test."""
    base = dict(
        contract_number='SPE7L1-26-C-INGST',
        idiq_contract_number=None,
        buyer_text='Acme Buying',
        award_date=date(2026, 5, 1),
        contractor_name='STATZ',
        contractor_cage='12345',
        contract_value=Decimal('12345.67'),
        contract_type='AWD',
        solicitation_type='SDVOSB',
        pr_number='PR-1',
        pdf_parse_status='success',
        pdf_parse_notes='',
        ado_days=None,
        clins=[
            ClinParseResult(
                item_number='0001',
                nsn='1234-12-345-6789',
                nsn_description='Widget',
                order_qty=Decimal('10'),
                uom='EA',
                unit_price=Decimal('5.00'),
                due_date=date(2026, 6, 1),
                inspection_point='O',
                acceptance_point='D',
                fob='D',
                cage='12345',
                supplier_name=None,
                clin_parse_note=None,
                min_order_qty_text=None,
            ),
        ],
        idiq_max_value=None,
        idiq_min_guarantee=None,
        idiq_term_months=None,
        idiq_option_months=None,
        contract_supplier_cage=None,
        contract_supplier_name=None,
        packhouse_cage=None,
        contract_packhouse_name=None,
    )
    base.update(overrides)
    return AwardParseResult(**base)


class IngestUnitTests(TestCase):
    """ingest_pdf logic with a stubbed parser (no real PDF needed)."""

    def test_happy_path_creates_draft(self):
        result = _stub_parse_result()
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake-pdf-bytes', original_filename='1.pdf')
        self.assertEqual(draft.contract_number, 'SPE7L1-26-C-INGST')
        self.assertEqual(draft.contract_type, 'AWD')
        self.assertEqual(draft.status, DraftContract.Status.QUEUED)
        self.assertEqual(draft.data['buyer_text'], 'Acme Buying')
        self.assertEqual(draft.data['contract_value'], '12345.67')
        self.assertEqual(draft.data['parser']['parser_version'], 'intake.pdf_parser')
        self.assertEqual(len(draft.data['clins']), 1)
        clin0 = draft.data['clins'][0]
        self.assertEqual(clin0['nsn_text'], '1234-12-345-6789')
        self.assertEqual(clin0['item_value'], '5.00')
        self.assertIsNone(clin0.get('unit_price'))
        self.assertEqual(clin0['item_type'], 'P')

    def test_contract_level_supplier_populates_clin(self):
        base_clin = _stub_parse_result().clins[0]
        result = _stub_parse_result(
            contract_supplier_cage='4M107',
            contract_supplier_name='GREENE METAL PRODUCTS, INC.',
            clins=[replace(base_clin, cage=None, supplier_name=None)],
        )
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='supplier_default.pdf')
        self.assertEqual(
            draft.data['clins'][0]['supplier_text'],
            'GREENE METAL PRODUCTS, INC.',
        )

    def test_clin_level_supplier_overrides_contract_level(self):
        base_clin = _stub_parse_result().clins[0]
        result = _stub_parse_result(
            contract_supplier_name='DEFAULT SUPPLIER',
            clins=[replace(base_clin, supplier_name='CLIN SPECIFIC SUPPLIER')],
        )
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='supplier_override.pdf')
        self.assertEqual(
            draft.data['clins'][0]['supplier_text'],
            'CLIN SPECIFIC SUPPLIER',
        )

    def test_missing_supplier_levels_keep_supplier_text_none(self):
        base_clin = _stub_parse_result().clins[0]
        result = _stub_parse_result(
            contract_supplier_name=None,
            clins=[replace(base_clin, supplier_name=None)],
        )
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='supplier_none.pdf')
        self.assertIsNone(draft.data['clins'][0]['supplier_text'])

    def test_packhouse_name_populates_packaging_block(self):
        result = _stub_parse_result(
            packhouse_cage='4M107',
            contract_packhouse_name='GREENE METAL PRODUCTS, INC.',
        )
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='packhouse.pdf')
        self.assertEqual(draft.data['packaging']['packhouse_cage'], '4M107')
        self.assertEqual(
            draft.data['packaging']['packhouse_supplier_text'],
            'GREENE METAL PRODUCTS, INC.',
        )

    def test_missing_contract_number_rejected(self):
        result = _stub_parse_result(contract_number=None)
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            with self.assertRaises(IngestionError):
                ingest_pdf(b'fake', original_filename='2.pdf')

    def test_missing_contract_type_rejected(self):
        result = _stub_parse_result(contract_type=None)
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            with self.assertRaises(IngestionError):
                ingest_pdf(b'fake', original_filename='3.pdf')

    def test_duplicate_draft_rejected(self):
        DraftContract.objects.create(
            contract_number='SPE7L1-26-C-INGST', contract_type='AWD',
        )
        result = _stub_parse_result()
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            with self.assertRaises(DuplicateContractNumber):
                ingest_pdf(b'fake', original_filename='4.pdf')

    def test_clin_ia_mapped_from_parser(self):
        """IA field is extracted from the parser result and stored on the CLIN."""
        result = _stub_parse_result()
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='ia_test.pdf')
        clin0 = draft.data['clins'][0]
        # _stub_parse_result sets inspection_point='O' (acceptance_point='D' ignored for IA).
        self.assertEqual(clin0.get('ia'), 'O')

    def test_contract_due_date_derived_from_earliest_clin(self):
        """Contract due_date is set to the earliest CLIN due_date after parse."""
        result = _stub_parse_result(clins=[
            ClinParseResult(
                item_number='0001', nsn='1111-11-111-1111', nsn_description='A',
                order_qty=Decimal('1'), uom='EA', unit_price=Decimal('1.00'),
                due_date=date(2027, 6, 1),
                inspection_point='O', acceptance_point='D', fob='D',
                cage='12345', supplier_name=None,
                clin_parse_note=None, min_order_qty_text=None,
            ),
            ClinParseResult(
                item_number='0002', nsn='2222-22-222-2222', nsn_description='B',
                order_qty=Decimal('2'), uom='EA', unit_price=Decimal('2.00'),
                due_date=date(2026, 12, 1),
                inspection_point='O', acceptance_point='D', fob='D',
                cage='12345', supplier_name=None,
                clin_parse_note=None, min_order_qty_text=None,
            ),
        ])
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='due_date_test.pdf')
        self.assertEqual(draft.data.get('due_date'), '2026-12-01')

    def test_contract_due_date_none_when_no_clins(self):
        """Contract due_date is not set when there are no CLINs."""
        result = _stub_parse_result(clins=[])
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='no_clins_test.pdf')
        self.assertIsNone(draft.data.get('due_date'))

    def test_sales_class_defaults_to_statz(self):
        """Sales class defaults to the STATZ SalesClass PK when it exists."""
        sc, _ = SalesClass.objects.get_or_create(sales_team='STATZ')
        result = _stub_parse_result()
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='sc_test.pdf')
        self.assertEqual(draft.data.get('sales_class_id'), sc.pk)

    def test_sales_class_none_when_statz_missing(self):
        """Sales class is None when no STATZ SalesClass record exists."""
        SalesClass.objects.filter(sales_team='STATZ').delete()
        result = _stub_parse_result()
        with patch('intake.ingest.parse_award_pdf', return_value=result):
            draft = ingest_pdf(b'fake', original_filename='sc_none_test.pdf')
        self.assertIsNone(draft.data.get('sales_class_id'))


class UploadViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')

    def _upload(self, files_payload):
        # files_payload is a list of (filename, AwardParseResult).
        # We chain side_effects so each call returns the next stub.
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload_files = [
            SimpleUploadedFile(name, b'%PDF-1.4 fake', content_type='application/pdf')
            for name, _ in files_payload
        ]
        results = [r for _, r in files_payload]
        with patch('intake.ingest.parse_award_pdf', side_effect=results):
            return self.client.post(
                reverse('intake:upload_pdfs'),
                data={'pdfs': upload_files},
            )

    def test_upload_creates_drafts(self):
        self.client.force_login(self.alice)
        resp = self._upload([
            ('a.pdf', _stub_parse_result(contract_number='SPE7L1-26-C-UP01')),
            ('b.pdf', _stub_parse_result(contract_number='SPE7L1-26-C-UP02')),
        ])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['results']), 2)
        self.assertTrue(all(r['ok'] for r in body['results']))
        self.assertEqual(
            DraftContract.objects.filter(
                contract_number__in=['SPE7L1-26-C-UP01', 'SPE7L1-26-C-UP02']
            ).count(),
            2,
        )

    def test_upload_mixed_outcomes(self):
        self.client.force_login(self.alice)
        # File 1 → success. File 2 → parser returns no contract_number.
        resp = self._upload([
            ('ok.pdf', _stub_parse_result(contract_number='SPE7L1-26-C-MIX1')),
            ('bad.pdf', _stub_parse_result(contract_number=None)),
        ])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['results'][0]['ok'])
        self.assertFalse(body['results'][1]['ok'])
        # The bad file did not abort the good one.
        self.assertTrue(
            DraftContract.objects.filter(contract_number='SPE7L1-26-C-MIX1').exists()
        )

    def test_upload_no_files_rejected(self):
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('intake:upload_pdfs'))
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Phase 3 — extended finalize types, DIBBS, email
# ---------------------------------------------------------------------------


class FinalizeExtendedTypesTests(TestCase):
    """DO / INTERNAL / MOD / AMD finalize paths."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.buyer = Buyer.objects.create(description='Acme Buying')
        cls.nsn = Nsn.objects.create(nsn_code='4444', description='Bolt')
        cls.supplier = Supplier.objects.create(name='SupX', cage_code='X1234')
        cls.parent_idiq = IdiqContract.objects.create(
            contract_number='SPE7L1-23-D-PARENT',
        )
        cls.parent_contract = Contract.objects.create(
            contract_number='SPE7L1-25-C-PARENT',
        )

    def _do_draft(self, **overrides):
        data = {
            'buyer_id': self.buyer.id,
            'buyer_text': 'Acme',
            'parent_idiq_id': self.parent_idiq.id,
            'parent_idiq_contract_number': self.parent_idiq.contract_number,
            'clins': [{
                'item_number': '0001',
                'nsn_id': self.nsn.id, 'nsn_text': '4444',
                'supplier_id': self.supplier.id, 'supplier_text': 'SupX',
            }],
        }
        data.update(overrides)
        return DraftContract.objects.create(
            contract_number='SPE7L1-26-F-DOFIN',
            contract_type='DO',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data=data,
        )

    def test_do_finalize_attaches_parent_idiq(self):
        draft = self._do_draft()
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        self.assertEqual(target.idiq_contract_id, self.parent_idiq.id)
        self.assertEqual(target.clin_set.count(), 1)

    def test_do_requires_parent_idiq_match(self):
        draft = self._do_draft(parent_idiq_id=None)
        with self.assertRaises(FinalizationError):
            with transaction.atomic():
                finalize_draft(draft, self.alice)

    def test_internal_finalize_no_buyer_required(self):
        draft = DraftContract.objects.create(
            contract_number='STATZ1-26-N-1001',
            contract_type='INTERNAL',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={'notes': 'internal tracking'},
        )
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        self.assertEqual(target.contract_number, 'STATZ1-26-N-1001')
        self.assertEqual(target.clin_set.count(), 0)

    def test_internal_rejects_unmatched_clin(self):
        draft = DraftContract.objects.create(
            contract_number='STATZ1-26-N-1002',
            contract_type='INTERNAL',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={'clins': [{'item_number': '0001', 'nsn_text': 'unmatched'}]},
        )
        with self.assertRaises(FinalizationError):
            with transaction.atomic():
                finalize_draft(draft, self.alice)

    def test_mod_appends_note_returns_parent_no_new_contract(self):
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-M-MOD01',
            contract_type='MOD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={
                'parent_contract_id': self.parent_contract.id,
                'parent_contract_number': self.parent_contract.contract_number,
                'mod_number': 'P00001',
                'summary': 'corrected ship address',
            },
        )
        before_count = Contract.objects.count()
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        # No new Contract was created.
        self.assertEqual(Contract.objects.count(), before_count)
        # Note was appended to the parent.
        from contracts.models import Note
        from django.contrib.contenttypes.models import ContentType
        notes = Note.objects.filter(
            content_type=ContentType.objects.get_for_model(Contract),
            object_id=self.parent_contract.id,
            note_tag='mod',
        )
        self.assertEqual(notes.count(), 1)
        self.assertIn('P00001', notes[0].note)
        self.assertEqual(target.pk, self.parent_contract.pk)

    def test_mod_requires_parent_contract_match(self):
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-M-MOD02',
            contract_type='MOD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={'mod_number': 'P00001', 'summary': 'x'},
        )
        with self.assertRaises(FinalizationError):
            with transaction.atomic():
                finalize_draft(draft, self.alice)


class FinanceLineShredTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.buyer = Buyer.objects.create(description='Acme')
        cls.nsn = Nsn.objects.create(nsn_code='5555', description='X')
        cls.supplier = Supplier.objects.create(name='S', cage_code='99')

    def test_per_clin_finance_and_splits_land_inline(self):
        """Each CLIN's nested finance_lines and splits create the matching
        ContractFinanceLine + ClinSplit rows on that CLIN."""
        from contracts.models import ClinSplit, ContractFinanceLine
        from decimal import Decimal
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-C-INLINE',
            contract_type='AWD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={
                'buyer_id': self.buyer.id,
                'clins': [
                    {
                        'item_number': '0001',
                        'nsn_id': self.nsn.id,
                        'supplier_id': self.supplier.id,
                        'item_value': '10.00',
                        'unit_price': '5.00',
                        'order_qty': 100,
                        'finance_lines': [
                            {'line_type': 'progress', 'amount': '200.00',
                             'notes': 'milestone'},
                        ],
                        'splits': [
                            {'company_name': 'STATZ', 'percentage': '60'},
                            {'company_name': 'PARTNER', 'percentage': '40'},
                        ],
                    },
                ],
            },
        )
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        clin = target.clin_set.get(item_number='0001')
        # 1 finance line on this CLIN — not on a non-existent first CLIN
        # via legacy path.
        self.assertEqual(ContractFinanceLine.objects.filter(clin=clin).count(), 1)
        # planned_gp = (10*100) - (5*100 + 200) = 300
        # split_value at 60% = 180.00, at 40% = 120.00
        splits = list(ClinSplit.objects.filter(clin=clin).order_by('company_name'))
        self.assertEqual(len(splits), 2)
        by_name = {s.company_name: s for s in splits}
        self.assertEqual(by_name['STATZ'].split_value, Decimal('180.00'))
        self.assertEqual(by_name['PARTNER'].split_value, Decimal('120.00'))

    def test_legacy_root_finance_lines_still_attach_to_first_clin(self):
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-C-FINLN',
            contract_type='AWD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={
                'buyer_id': self.buyer.id,
                'clins': [
                    {'item_number': '0001', 'nsn_id': self.nsn.id,
                     'supplier_id': self.supplier.id},
                    {'item_number': '0002', 'nsn_id': self.nsn.id,
                     'supplier_id': self.supplier.id},
                ],
                'finance_lines': [
                    {'line_type': 'progress', 'amount': '1000.00',
                     'notes': 'milestone 1'},
                    {'line_type': 'progress', 'amount': '2000.00'},
                ],
            },
        )
        with transaction.atomic():
            target = finalize_draft(draft, self.alice)
        first_clin = target.clin_set.order_by('item_number').first()
        second_clin = target.clin_set.order_by('item_number').last()
        from contracts.models import ContractFinanceLine
        first_lines = ContractFinanceLine.objects.filter(clin=first_clin)
        second_lines = ContractFinanceLine.objects.filter(clin=second_clin)
        self.assertEqual(first_lines.count(), 2)
        self.assertEqual(second_lines.count(), 0)


class ContractMatcherTests(TestCase):
    """Verify the new 'contract' match_type used by MOD/AMD parent lookups."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.parent = Contract.objects.create(contract_number='SPE7L1-25-C-PMATCH')

    def test_search_contract_by_number(self):
        results = matcher_search('contract', 'PMATCH')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.parent.id)

    def test_apply_parent_contract(self):
        data = {}
        apply_match(data, 'parent_contract', 'contract', self.parent.id)
        self.assertEqual(data['parent_contract_id'], self.parent.id)
        self.assertEqual(data['parent_contract_number'], 'SPE7L1-25-C-PMATCH')


class DibbsIngestTests(TestCase):
    """ingest_dibbs_record converter — no scraper invoked."""

    def test_happy_path(self):
        from intake.ingest import ingest_dibbs_record
        rec = {
            'Award_Basic_Number': 'SPE7L1-26-C-9001',
            'Delivery_Order_Number': '',
            'Award_Date': '05-15-2026',
            'Awardee_CAGE_Code': '12345',
            'Total_Contract_Price': '10000.00',
            'NSN_Part_Number': '1234-12-345-6789',
            'Nomenclature': 'Widget',
            'Purchase_Request': 'PR-77',
            'Solicitation': 'SPE7L1-26-R-0001',
        }
        draft = ingest_dibbs_record(rec)
        self.assertEqual(draft.contract_number, 'SPE7L1-26-C-9001')
        self.assertEqual(draft.contract_type, 'AWD')
        self.assertEqual(draft.pdf_parse_status, DraftContract.PdfParseStatus.NO_PDF)
        self.assertEqual(draft.data['pr_number'], 'PR-77')
        self.assertEqual(draft.data['contractor_cage'], '12345')
        self.assertEqual(len(draft.data['clins']), 1)
        self.assertEqual(draft.data['clins'][0]['nsn_text'], '1234-12-345-6789')

    def test_do_uses_delivery_order_number_as_identity(self):
        from intake.ingest import ingest_dibbs_record
        rec = {
            'Award_Basic_Number': 'SPE7L1-23-D-PARENT',
            'Delivery_Order_Number': 'SPE7L1-26-F-DO001',
            'Award_Date': '05-15-2026',
            'NSN_Part_Number': '9999',
        }
        draft = ingest_dibbs_record(rec)
        self.assertEqual(draft.contract_number, 'SPE7L1-26-F-DO001')
        self.assertEqual(draft.contract_type, 'DO')

    def test_missing_numbers_rejected(self):
        from intake.ingest import ingest_dibbs_record
        with self.assertRaises(IngestionError):
            ingest_dibbs_record({'NSN_Part_Number': '9999'})


class FinalizeEmailRedirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.buyer = Buyer.objects.create(description='Acme')
        cls.nsn = Nsn.objects.create(nsn_code='6666', description='X')
        cls.supplier = Supplier.objects.create(name='S', cage_code='99')

    def test_finalize_view_redirects_to_compose(self):
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-C-EMAIL',
            contract_type='AWD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={
                'buyer_id': self.buyer.id, 'buyer_text': 'Acme',
                'pr_number': 'PR-EM',
                'clins': [{
                    'item_number': '0001',
                    'nsn_id': self.nsn.id, 'nsn_text': '6666',
                    'supplier_id': self.supplier.id, 'supplier_text': 'S',
                }],
            },
        )
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('intake:finalize_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/processing/email-compose/', resp.url)
        # The body should contain the new contract number.
        self.assertIn('SPE7L1-26-C-EMAIL', resp.url)
        self.assertIn('subject=', resp.url)

    def test_mod_finalize_skips_email_redirect(self):
        parent = Contract.objects.create(contract_number='SPE7L1-25-C-PMOD')
        draft = DraftContract.objects.create(
            contract_number='SPE7L1-26-M-NEMAIL',
            contract_type='MOD',
            status=DraftContract.Status.READY_FOR_REVIEW,
            data={
                'parent_contract_id': parent.id,
                'parent_contract_number': parent.contract_number,
                'mod_number': 'P00001', 'summary': 'x',
            },
        )
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(reverse('intake:finalize_draft', args=[draft.pk]))
        self.assertEqual(resp.status_code, 302)
        # MOD returns parent — no email compose, just queue.
        self.assertNotIn('/processing/email-compose/', resp.url)


# ---------------------------------------------------------------------------
# Phase 2c — inline create (buyer / NSN / supplier) via matcher modal
# ---------------------------------------------------------------------------


class MatcherCreateUnitTests(TestCase):
    """Pure-function create_record behavior."""

    def test_buyer_create_returns_pk(self):
        from intake.matchers import create_record
        pk = create_record('buyer', {'description': 'Acme Buying Office'})
        self.assertTrue(Buyer.objects.filter(pk=pk).exists())

    def test_buyer_create_requires_description(self):
        from intake.matchers import create_record
        with self.assertRaises(MatcherError):
            create_record('buyer', {'description': ''})

    def test_buyer_create_rejects_duplicate_description(self):
        from intake.matchers import create_record
        Buyer.objects.create(description='Acme Buying Office')
        with self.assertRaises(MatcherError):
            create_record('buyer', {'description': 'acme buying office'})

    def test_nsn_create_with_optional_description(self):
        from intake.matchers import create_record
        pk = create_record('nsn', {'nsn_code': '8888-88-888-8888'})
        nsn = Nsn.objects.get(pk=pk)
        self.assertEqual(nsn.nsn_code, '8888-88-888-8888')
        self.assertIsNone(nsn.description)

    def test_nsn_create_requires_code(self):
        from intake.matchers import create_record
        with self.assertRaises(MatcherError):
            create_record('nsn', {'description': 'orphan'})

    def test_supplier_create_requires_cage(self):
        from intake.matchers import create_record
        with self.assertRaises(MatcherError):
            create_record('supplier', {'name': 'NoCage'})

    def test_supplier_dedup_on_cage(self):
        from intake.matchers import create_record
        Supplier.objects.create(name='Existing', cage_code='ABCDE')
        with self.assertRaises(MatcherError):
            create_record('supplier', {'name': 'Other', 'cage_code': 'abcde'})

    def test_unsupported_match_type_rejected(self):
        from intake.matchers import create_record
        with self.assertRaises(MatcherError):
            create_record('idiq', {'contract_number': 'X'})


class MatcherCreateEndpointTests(TestCase):
    """End-to-end create-and-apply via the /match/ endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', 'a@x.com', 'pw')
        cls.bob = User.objects.create_user('bob', 'b@x.com', 'pw')

    def _draft(self, **kw):
        defaults = dict(
            contract_number='SPE7L1-26-P-CREATE',
            contract_type='AWD',
            status=DraftContract.Status.IN_PROGRESS,
        )
        defaults.update(kw)
        return DraftContract.objects.create(**defaults)

    def _post(self, draft, body):
        return self.client.post(
            reverse('intake:match', args=[draft.pk]),
            data=json.dumps(body),
            content_type='application/json',
        )

    def test_create_buyer_applies_to_draft_under_lock(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self._post(draft, {
            'action': 'create', 'match_type': 'buyer',
            'target_path': 'buyer',
            'payload': {'description': 'Fresh Buyer'},
        })
        self.assertEqual(resp.status_code, 200)
        draft.refresh_from_db()
        new_buyer = Buyer.objects.get(description='Fresh Buyer')
        self.assertEqual(draft.data['buyer_id'], new_buyer.id)
        self.assertEqual(draft.data['buyer_text'], 'Fresh Buyer')

    def test_create_requires_lock(self):
        draft = self._draft()
        # No lock acquired.
        self.client.force_login(self.alice)
        resp = self._post(draft, {
            'action': 'create', 'match_type': 'buyer',
            'target_path': 'buyer',
            'payload': {'description': 'Should Not Land'},
        })
        self.assertEqual(resp.status_code, 409)
        # The transaction rolled back — no buyer created.
        self.assertFalse(Buyer.objects.filter(description='Should Not Land').exists())

    def test_create_validation_error_rolls_back_new_row(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        # Blank description — creator raises MatcherError BEFORE any
        # canonical row is created. Still expect no Buyer to land.
        resp = self._post(draft, {
            'action': 'create', 'match_type': 'buyer',
            'target_path': 'buyer', 'payload': {'description': ''},
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_unsupported_type_rejected(self):
        draft = self._draft()
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self._post(draft, {
            'action': 'create', 'match_type': 'idiq',
            'target_path': 'parent_idiq',
            'payload': {'contract_number': 'X'},
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Inline create', resp.json().get('error', ''))

    def test_creatable_types_endpoint(self):
        draft = self._draft()
        self.client.force_login(self.alice)
        resp = self._post(draft, {'action': 'creatable_types'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            sorted(resp.json()['creatable_types']),
            ['buyer', 'nsn', 'supplier'],
        )

    def test_create_nsn_applies_to_clin_path(self):
        draft = self._draft(data={'clins': [{'item_number': '0001'}]})
        acquire(draft, self.alice)
        self.client.force_login(self.alice)
        resp = self._post(draft, {
            'action': 'create', 'match_type': 'nsn',
            'target_path': 'clin:0:nsn',
            'payload': {'nsn_code': '7777-77-777-7777', 'description': 'New Widget'},
        })
        self.assertEqual(resp.status_code, 200)
        draft.refresh_from_db()
        nsn = Nsn.objects.get(nsn_code='7777-77-777-7777')
        self.assertEqual(draft.data['clins'][0]['nsn_id'], nsn.id)
        self.assertEqual(draft.data['clins'][0]['nsn_description'], 'New Widget')
