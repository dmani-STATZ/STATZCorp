"""
Tests for the CLIN Fix tool (sunset cleanup).

Run with:
    python manage.py test contracts.tests.test_clin_fix
"""
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from contracts.models import (
    Clin,
    ClinReclassificationDraft,
    ClinReclassificationLog,
    ClinShipment,
    Company,
    Contract,
    ContractFinanceLine,
    ContractPackaging,
    ContractStatus,
    FinanceLinePayment,
    Note,
    PaymentHistory,
)
from suppliers.models import Supplier
from users.models import UserCompanyMembership


def _create_company(name='Test Co', slug=None):
    slug = slug or name.lower().replace(' ', '-')
    return Company.objects.create(name=name, slug=slug, is_active=True)


def _create_user(username='tester', password='testpw12345', company=None,
                 is_superuser=False, is_staff=False):
    user = User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password=password,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )
    if company is not None:
        UserCompanyMembership.objects.create(user=user, company=company, is_default=True)
    return user


def _create_contract(company, contract_number='C-0001'):
    return Contract.objects.create(
        contract_number=contract_number,
        company=company,
    )


def _create_clin(contract, item_number='0001', **kwargs):
    defaults = {
        'company': contract.company,
        'contract': contract,
        'item_number': item_number,
    }
    defaults.update(kwargs)
    return Clin.objects.create(**defaults)


def _create_supplier(name='Acme Supplies', cage='1A2B3'):
    return Supplier.objects.create(name=name, cage_code=cage)


@override_settings(REQUIRE_LOGIN=False)
class ClinFixBaseTest(TestCase):
    """Common setup for CLIN Fix view tests."""

    def setUp(self):
        self.company = _create_company('Co A', 'co-a')
        self.user = _create_user('user_a', company=self.company)
        self.client = Client()
        self.client.login(username='user_a', password='testpw12345')
        # Ensure the session has the active company so middleware resolves it
        session = self.client.session
        session['active_company_id'] = self.company.id
        session.save()


@override_settings(REQUIRE_LOGIN=False)
class ClinFixConversionTests(ClinFixBaseTest):

    def test_clin_to_packaging_field_mapping(self):
        supplier = _create_supplier()
        contract = _create_contract(self.company)
        clin = _create_clin(
            contract,
            item_number='0010',
            supplier=supplier,
            quote_value=Decimal('1500.00'),
            paid_amount=Decimal('1500.00'),
            paid_date=timezone.now().date(),
            item_type='M',
        )
        # Add another CLIN so finance_line guards have a target if needed
        _create_clin(contract, item_number='0001', item_value=Decimal('5000'))

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': clin.id,
            'destination_type': 'packaging',
            'staged_data': {},
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['conversion_count'], 1)

        # Packaging created
        pkg = ContractPackaging.objects.get(contract=contract)
        self.assertEqual(pkg.packhouse_id, supplier.id)
        self.assertEqual(pkg.quote_amount, Decimal('1500.00'))
        self.assertEqual(pkg.amount_paid, Decimal('1500.00'))
        self.assertIsNotNone(pkg.payment_date)
        self.assertIn('Migrated from CLIN 0010', pkg.notes or '')

        # Log row exists with full snapshot
        log = ClinReclassificationLog.objects.get(
            contract=contract, original_clin_id=clin.id
        )
        self.assertEqual(log.destination_type, 'packaging')
        self.assertEqual(log.destination_id, pkg.id)
        self.assertIsNotNone(log.original_data)
        self.assertEqual(log.original_data.get('item_number'), '0010')

        # Original CLIN gone
        self.assertFalse(Clin.objects.filter(id=clin.id).exists())

    def test_clin_to_finance_line_field_mapping(self):
        contract = _create_contract(self.company, 'C-FL')
        target_clin = _create_clin(contract, item_number='0001', item_value=Decimal('100'))
        legacy_clin = _create_clin(
            contract,
            item_number='0099',
            quote_value=Decimal('250.00'),
            paid_amount=Decimal('250.00'),
            paid_date=timezone.now().date(),
        )

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': legacy_clin.id,
            'destination_type': 'finance_line',
            'staged_data': {'line_type': 'Trucking'},
            'parent_clin_id': target_clin.id,
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)

        fl = ContractFinanceLine.objects.get(clin=target_clin)
        self.assertEqual(fl.line_type, 'Trucking')
        self.assertEqual(fl.amount_billed, Decimal('250.00'))
        self.assertIsNone(fl.partial_id)
        # FinanceLinePayment auto-created
        payment = FinanceLinePayment.objects.get(finance_line=fl)
        self.assertEqual(payment.amount, Decimal('250.00'))

        log = ClinReclassificationLog.objects.get(
            contract=contract, original_clin_id=legacy_clin.id
        )
        self.assertEqual(log.destination_type, 'finance_line')
        self.assertEqual(log.destination_id, fl.id)

    def test_clin_to_finance_line_no_paid_amount_skips_payment(self):
        contract = _create_contract(self.company, 'C-FL2')
        target_clin = _create_clin(contract, item_number='0001')
        legacy_clin = _create_clin(
            contract,
            item_number='0099',
            quote_value=Decimal('100.00'),
            paid_amount=None,
        )
        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': legacy_clin.id,
            'destination_type': 'finance_line',
            'staged_data': {'line_type': 'Freight'},
            'parent_clin_id': target_clin.id,
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        fl = ContractFinanceLine.objects.get(clin__contract=contract)
        self.assertEqual(FinanceLinePayment.objects.filter(finance_line=fl).count(), 0)

    def test_clin_to_partial_shipment_field_mapping(self):
        contract = _create_contract(self.company, 'C-PS')
        parent = _create_clin(contract, item_number='0001', uom='EA')
        legacy = _create_clin(
            contract,
            item_number='0099',
            ship_qty=10,
            uom='EA',
            ship_date=timezone.now().date(),
            quote_value=Decimal('200.00'),
            item_value=Decimal('300.00'),
            paid_amount=Decimal('150.00'),
            wawf_payment=Decimal('120.00'),
        )

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': legacy.id,
            'destination_type': 'partial_shipment',
            'staged_data': {
                'comments': 'extra note',
                'quote_value': '450.00',
                'item_value': '500.00',
            },
            'parent_clin_id': parent.id,
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)

        ship = ClinShipment.objects.get(clin=parent)
        self.assertEqual(ship.ship_qty, 10)
        # staged_data values should take priority over source CLIN values
        self.assertEqual(ship.quote_value, Decimal('450.00'))
        self.assertEqual(ship.item_value, Decimal('500.00'))
        self.assertEqual(ship.paid_amount, Decimal('150.00'))
        self.assertEqual(ship.wawf_payment, Decimal('120.00'))
        self.assertIn('Migrated from CLIN 0099', ship.comments or '')

        log = ClinReclassificationLog.objects.get(
            contract=contract, original_clin_id=legacy.id
        )
        self.assertEqual(log.destination_type, 'partial_shipment')
        self.assertEqual(log.destination_id, ship.id)

    def test_notes_migrated_to_contract(self):
        contract = _create_contract(self.company, 'C-NM')
        _create_clin(contract, item_number='0001', item_value=Decimal('1'))
        clin = _create_clin(contract, item_number='0099')

        clin_ct = ContentType.objects.get_for_model(Clin)
        contract_ct = ContentType.objects.get_for_model(Contract)
        for i in range(3):
            Note.objects.create(
                content_type=clin_ct,
                object_id=clin.id,
                note=f"original note {i}",
                company=self.company,
                created_by=self.user,
            )

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': clin.id,
            'destination_type': 'deleted',
            'staged_data': {'reason': 'garbage row'},
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)

        # All notes now point to the Contract
        notes = Note.objects.filter(content_type=contract_ct, object_id=contract.id)
        self.assertEqual(notes.count(), 3)
        for n in notes:
            self.assertTrue((n.note or '').startswith('[Migrated from CLIN 0099]'))

        log = ClinReclassificationLog.objects.get(
            contract=contract, original_clin_id=clin.id
        )
        self.assertEqual(log.notes_migrated_count, 3)

    def test_payment_history_deleted(self):
        contract = _create_contract(self.company, 'C-PH')
        _create_clin(contract, item_number='0001', item_value=Decimal('1'))
        clin = _create_clin(contract, item_number='0099')
        clin_ct = ContentType.objects.get_for_model(Clin)
        for _ in range(2):
            PaymentHistory.objects.create(
                content_type=clin_ct,
                object_id=clin.id,
                payment_type='paid_amount',
                payment_amount=Decimal('50.00'),
                payment_date=timezone.now().date(),
                created_by=self.user,
            )

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': clin.id,
            'destination_type': 'deleted',
            'staged_data': {'reason': 'remove'},
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)

        self.assertEqual(
            PaymentHistory.objects.filter(content_type=clin_ct, object_id=clin.id).count(),
            0,
        )
        log = ClinReclassificationLog.objects.get(original_clin_id=clin.id)
        self.assertEqual(log.payment_history_deleted_count, 2)

    def test_original_clin_hard_deleted(self):
        contract = _create_contract(self.company, 'C-HD')
        _create_clin(contract, item_number='0001', item_value=Decimal('1'))
        clin = _create_clin(contract, item_number='0099')
        original_id = clin.id

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': clin.id,
            'destination_type': 'deleted',
            'staged_data': {'reason': 'remove'},
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(Clin.objects.filter(id=original_id).exists())
        log = ClinReclassificationLog.objects.get(original_clin_id=original_id)
        self.assertEqual(log.original_clin_id, original_id)


@override_settings(REQUIRE_LOGIN=False)
class ClinFixValidationTests(ClinFixBaseTest):

    def test_validation_blocks_packaging_when_exists(self):
        supplier = _create_supplier()
        contract = _create_contract(self.company, 'C-PE')
        _create_clin(contract, item_number='0001', item_value=Decimal('1'))
        clin = _create_clin(contract, item_number='0099', supplier=supplier)
        ContractPackaging.objects.create(contract=contract, packhouse=supplier)

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': clin.id,
            'destination_type': 'packaging',
            'staged_data': {},
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertFalse(body['success'])
        self.assertTrue(any('already has packaging' in e['error'].lower() for e in body['errors']))

        # No conversion happened
        self.assertTrue(Clin.objects.filter(id=clin.id).exists())
        self.assertEqual(
            ClinReclassificationLog.objects.filter(original_clin_id=clin.id).count(),
            0,
        )

    def test_validation_blocks_packaging_with_income_side(self):
        supplier = _create_supplier()
        contract = _create_contract(self.company, 'C-PI')
        _create_clin(contract, item_number='0001', item_value=Decimal('1'))
        clin = _create_clin(
            contract,
            item_number='0099',
            supplier=supplier,
            item_value=Decimal('500.00'),
        )

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': clin.id,
            'destination_type': 'packaging',
            'staged_data': {},
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertFalse(body['success'])
        self.assertTrue(any('income side' in e['error'].lower() for e in body['errors']))

    def test_validation_blocks_partial_shipment_without_parent(self):
        contract = _create_contract(self.company, 'C-NPP')
        _create_clin(contract, item_number='0001', item_value=Decimal('1'))
        clin = _create_clin(contract, item_number='0099')

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [{
            'clin_id': clin.id,
            'destination_type': 'partial_shipment',
            'staged_data': {},
            'parent_clin_id': None,
        }]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertFalse(body['success'])
        self.assertTrue(any('parent' in e['error'].lower() for e in body['errors']))

    def test_validation_blocks_partial_shipment_when_parent_also_being_converted(self):
        contract = _create_contract(self.company, 'C-PPC')
        a = _create_clin(contract, item_number='0001')
        b = _create_clin(contract, item_number='0002')
        # third remaining CLIN so finance_line still has a target
        _create_clin(contract, item_number='0003')
        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [
            {
                'clin_id': a.id,
                'destination_type': 'partial_shipment',
                'staged_data': {},
                'parent_clin_id': b.id,
            },
            {
                'clin_id': b.id,
                'destination_type': 'finance_line',
                'staged_data': {'line_type': 'Trucking'},
            },
        ]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertFalse(body['success'])

    def test_atomic_rollback_on_partial_failure(self):
        supplier = _create_supplier()
        contract = _create_contract(self.company, 'C-ATM')
        _create_clin(contract, item_number='0001', item_value=Decimal('1'))
        c1 = _create_clin(contract, item_number='0010', supplier=supplier)
        c2 = _create_clin(contract, item_number='0011')
        # third one has income side; will fail packaging validation
        c3 = _create_clin(contract, item_number='0012', item_value=Decimal('500.00'))

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [
            {
                'clin_id': c1.id,
                'destination_type': 'packaging',
                'staged_data': {},
            },
            {
                'clin_id': c2.id,
                'destination_type': 'deleted',
                'staged_data': {'reason': 'junk'},
            },
            {
                'clin_id': c3.id,
                'destination_type': 'packaging',
                'staged_data': {},
            },
        ]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        # Multiple-packaging guard or income guard fires before any commit
        self.assertTrue(Clin.objects.filter(id=c1.id).exists())
        self.assertTrue(Clin.objects.filter(id=c2.id).exists())
        self.assertTrue(Clin.objects.filter(id=c3.id).exists())
        self.assertEqual(ContractPackaging.objects.filter(contract=contract).count(), 0)
        self.assertEqual(
            ClinReclassificationLog.objects.filter(contract=contract).count(),
            0,
        )


@override_settings(REQUIRE_LOGIN=False)
class ClinFixDraftTests(ClinFixBaseTest):

    def test_drafts_deleted_on_successful_save(self):
        contract = _create_contract(self.company, 'C-DD')
        _create_clin(contract, item_number='0001', item_value=Decimal('1'))
        c2 = _create_clin(contract, item_number='0010')
        c3 = _create_clin(contract, item_number='0011')
        for clin in (c2, c3):
            ClinReclassificationDraft.objects.create(
                contract=contract,
                user=self.user,
                clin=clin,
                destination_type='deleted',
                staged_data={'reason': 'junk'},
            )
        self.assertEqual(
            ClinReclassificationDraft.objects.filter(contract=contract, user=self.user).count(),
            2,
        )

        url = reverse('contracts:clin_fix_save', args=[contract.pk])
        payload = {'conversions': [
            {'clin_id': c2.id, 'destination_type': 'deleted', 'staged_data': {'reason': 'junk'}},
            {'clin_id': c3.id, 'destination_type': 'deleted', 'staged_data': {'reason': 'junk'}},
        ]}
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            ClinReclassificationDraft.objects.filter(contract=contract, user=self.user).count(),
            0,
        )

    def test_draft_autosave_upsert(self):
        contract = _create_contract(self.company, 'C-AS')
        clin = _create_clin(contract, item_number='0010')

        url = reverse('contracts:clin_fix_draft_save', args=[contract.pk])
        body1 = {
            'clin_id': clin.id,
            'destination_type': 'deleted',
            'staged_data': {'reason': 'first'},
        }
        resp1 = self.client.post(url, data=json.dumps(body1), content_type='application/json')
        self.assertEqual(resp1.status_code, 200, resp1.content)

        body2 = {
            'clin_id': clin.id,
            'destination_type': 'deleted',
            'staged_data': {'reason': 'second'},
        }
        resp2 = self.client.post(url, data=json.dumps(body2), content_type='application/json')
        self.assertEqual(resp2.status_code, 200, resp2.content)

        drafts = ClinReclassificationDraft.objects.filter(
            contract=contract, user=self.user, clin=clin,
        )
        self.assertEqual(drafts.count(), 1)
        self.assertEqual(drafts.first().staged_data.get('reason'), 'second')

    def test_draft_autosave_default_deletes_draft(self):
        contract = _create_contract(self.company, 'C-DEF')
        clin = _create_clin(contract, item_number='0010')

        ClinReclassificationDraft.objects.create(
            contract=contract,
            user=self.user,
            clin=clin,
            destination_type='deleted',
            staged_data={'reason': 'x'},
        )
        url = reverse('contracts:clin_fix_draft_save', args=[contract.pk])
        resp = self.client.post(
            url,
            data=json.dumps({'clin_id': clin.id, 'destination_type': 'default'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            ClinReclassificationDraft.objects.filter(
                contract=contract, user=self.user, clin=clin,
            ).exists()
        )

    def test_other_contract_drafts_widget_data(self):
        # User has drafts on contracts B and C; opens page for contract A
        a = _create_contract(self.company, 'C-A')
        b = _create_contract(self.company, 'C-B')
        c = _create_contract(self.company, 'C-C')
        b_clin = _create_clin(b, item_number='0001')
        c_clin = _create_clin(c, item_number='0001')
        ClinReclassificationDraft.objects.create(
            contract=b, user=self.user, clin=b_clin,
            destination_type='deleted', staged_data={'reason': 'x'},
        )
        ClinReclassificationDraft.objects.create(
            contract=c, user=self.user, clin=c_clin,
            destination_type='deleted', staged_data={'reason': 'x'},
        )

        url = reverse('contracts:clin_fix_page', args=[a.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        other = resp.context['other_contract_drafts']
        contract_pks = [row['contract_pk'] for row in other]
        self.assertIn(b.pk, contract_pks)
        self.assertIn(c.pk, contract_pks)
        self.assertNotIn(a.pk, contract_pks)
        # Ordering descending by last_updated; both have similar timestamps but the
        # second-created row should be first.
        self.assertEqual(other[0]['contract_pk'], c.pk)

    def test_other_contract_drafts_caps_at_10(self):
        a = _create_contract(self.company, 'C-MAIN')
        for i in range(15):
            other = _create_contract(self.company, f'C-X{i:02d}')
            clin = _create_clin(other, item_number='0001')
            ClinReclassificationDraft.objects.create(
                contract=other, user=self.user, clin=clin,
                destination_type='deleted', staged_data={'reason': 'x'},
            )
        url = reverse('contracts:clin_fix_page', args=[a.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        other = resp.context['other_contract_drafts']
        self.assertEqual(len(other), 10)


@override_settings(REQUIRE_LOGIN=False)
class ClinFixCompanyScopingTest(TestCase):

    def test_company_scoping(self):
        company_x = _create_company('Co X', 'co-x')
        company_y = _create_company('Co Y', 'co-y')
        contract = _create_contract(company_x, 'C-X')

        user = _create_user('scopeuser', company=company_y)
        client = Client()
        client.login(username='scopeuser', password='testpw12345')
        session = client.session
        session['active_company_id'] = company_y.id
        session.save()

        url = reverse('contracts:clin_fix_page', args=[contract.pk])
        resp = client.get(url)
        self.assertEqual(resp.status_code, 404)