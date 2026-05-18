"""Tests: model dedup, schema validation, lock semantics, editor flow."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from intake.forms_parse import parse_post
from intake.locks import (
    LOCK_DURATION,
    LockError,
    acquire,
    assert_holds,
    clear_expired,
    is_expired,
    release,
)
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
