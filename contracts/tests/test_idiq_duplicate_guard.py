"""IDIQ duplicate guard, safe delete, close / reopen, and the duplicate report."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from contracts.models import Company, Contract, IdiqContract, get_idiq_dependents
from contracts.services.contract_create import ContractCreationError, create_idiq_from_payload
from contracts.services.contract_number import normalize_idiq_number
from transactions.models import Transaction
from users.models import UserCompanyMembership


class IdiqGuardTestBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Idiq Guard Co', slug='idiq-guard-co')
        self.user = get_user_model().objects.create_user('idiq-guard', password='x')
        UserCompanyMembership.objects.create(user=self.user, company=self.company, is_default=True)
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()
        self.idiq = IdiqContract.objects.create(
            company=self.company, contract_number='SPE7L1-23-D-0099', closed=False,
        )


class NormalizeIdiqNumberTests(TestCase):
    def test_strips_dashes_spaces_and_uppercases(self):
        self.assertEqual(normalize_idiq_number('  spe7l1-23 d-0099 '), 'SPE7L123D0099')
        self.assertEqual(normalize_idiq_number(None), '')


class DuplicateCreateTests(IdiqGuardTestBase):
    def _create(self, number):
        return create_idiq_from_payload(
            {'company': self.company, 'contract_number': number}, self.user,
        )

    def test_dash_case_and_whitespace_variants_rejected(self):
        for variant in ('SPE7L123D0099', 'spe7l1-23-d-0099', '  SPE7L1 23 D 0099  '):
            with self.subTest(variant=variant):
                with self.assertRaises(ContractCreationError) as ctx:
                    self._create(variant)
                self.assertIn('IDIQ SPE7L1-23-D-0099 already exists (status: Open)', str(ctx.exception))
        self.assertEqual(IdiqContract.objects.count(), 1)

    def test_closed_existing_rejected_with_reopen_hint(self):
        self.idiq.closed = True
        self.idiq.save()
        with self.assertRaises(ContractCreationError) as ctx:
            self._create('spe7l1-23-d-0099')
        self.assertIn('(status: Closed)', str(ctx.exception))
        self.assertTrue(str(ctx.exception).endswith('Reopen it if this IDIQ is still active.'))

    def test_new_number_created_and_audited(self):
        idiq = self._create('SPE7L1-23-D-0100')
        ct = ContentType.objects.get_for_model(IdiqContract)
        self.assertTrue(
            Transaction.objects.filter(content_type=ct, object_id=idiq.pk, note='IDIQ created').exists()
        )


class DuplicateEditTests(IdiqGuardTestBase):
    def test_edit_keeping_own_number_allowed(self):
        url = reverse('contracts:idiq_contract_update', args=[self.idiq.pk])
        response = self.client.post(url, {'contract_number': 'spe7l1-23-d-0099'})
        self.assertEqual(response.status_code, 302)

    def test_edit_to_another_idiq_number_rejected(self):
        other = IdiqContract.objects.create(company=self.company, contract_number='SPE7L1-23-D-0200')
        url = reverse('contracts:idiq_contract_update', args=[other.pk])
        response = self.client.post(url, {'contract_number': 'SPE7L1 23 D 0099'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'IDIQ SPE7L1-23-D-0099 already exists (status: Open).')
        other.refresh_from_db()
        self.assertEqual(other.contract_number, 'SPE7L1-23-D-0200')


class DeleteGuardTests(IdiqGuardTestBase):
    def test_get_rejected(self):
        response = self.client.get(reverse('contracts:idiq_contract_delete', args=[self.idiq.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(IdiqContract.objects.filter(pk=self.idiq.pk).exists())

    def test_delete_refused_with_dependents(self):
        Contract.objects.create(
            company=self.company, contract_number='SPE7L1-23-F-0001', idiq_contract=self.idiq,
        )
        self.assertEqual(get_idiq_dependents(self.idiq), [('Delivery orders', 1)])
        response = self.client.post(
            reverse('contracts:idiq_contract_delete', args=[self.idiq.pk]), follow=True,
        )
        self.assertTrue(IdiqContract.objects.filter(pk=self.idiq.pk).exists())
        self.assertContains(response, 'Delivery orders (1)')
        self.assertContains(response, 'If it is a duplicate, ask Dion to merge it.')

    def test_delete_succeeds_without_dependents(self):
        pk = self.idiq.pk
        response = self.client.post(reverse('contracts:idiq_contract_delete', args=[pk]))
        self.assertRedirects(response, reverse('contracts:idiq_list'), fetch_redirect_response=False)
        self.assertFalse(IdiqContract.objects.filter(pk=pk).exists())
        ct = ContentType.objects.get_for_model(IdiqContract)
        self.assertTrue(Transaction.objects.filter(content_type=ct, object_id=pk, note='IDIQ deleted').exists())


class CloseReopenTests(IdiqGuardTestBase):
    def test_close_then_reopen(self):
        ct = ContentType.objects.get_for_model(IdiqContract)
        self.client.post(reverse('contracts:idiq_contract_close', args=[self.idiq.pk]))
        self.idiq.refresh_from_db()
        self.assertTrue(self.idiq.closed)

        self.client.post(reverse('contracts:idiq_contract_reopen', args=[self.idiq.pk]))
        self.idiq.refresh_from_db()
        self.assertFalse(self.idiq.closed)
        self.assertEqual(
            Transaction.objects.filter(content_type=ct, object_id=self.idiq.pk, field_name='closed').count(), 2,
        )

    def test_close_rejects_get(self):
        response = self.client.get(reverse('contracts:idiq_contract_close', args=[self.idiq.pk]))
        self.assertEqual(response.status_code, 405)


class FindDuplicateIdiqsCommandTests(IdiqGuardTestBase):
    def test_lists_seeded_duplicate_group(self):
        dup = IdiqContract.objects.create(
            company=self.company, contract_number='spe7l1 23 d 0099', closed=True,
        )
        IdiqContract.objects.create(company=self.company, contract_number='SPE7L1-23-D-0300')
        out = StringIO()
        call_command('find_duplicate_idiqs', stdout=out)
        output = out.getvalue()
        self.assertIn('SPE7L123D0099 (2 records)', output)
        self.assertIn(f'pk={self.idiq.pk}', output)
        self.assertIn(f'pk={dup.pk}', output)
        self.assertIn('status=Closed', output)
        self.assertNotIn('SPE7L123D0300', output)
        self.assertTrue(output.strip().endswith('Duplicate groups: 1'))
