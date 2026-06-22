"""Smoke tests for `contracts.services.contract_create`.

Run with:
    python manage.py test contracts.tests.test_create_service
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.test import TestCase

from contracts.models import (
    Buyer,
    Clin,
    ClinSplit,
    Contract,
    ContractFinanceLine,
    ContractPackaging,
    IdiqContract,
    IdiqContractDetails,
    Note,
    PaymentHistory,
    SalesClass,
)
from contracts.services import (
    ContractCreationError,
    create_contract_from_payload,
    create_idiq_from_payload,
)
from products.models import Nsn
from suppliers.models import Supplier


class ContractCreationServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='svc-tester', password='pw')
        cls.buyer = Buyer.objects.create(description='Buying Office')
        cls.sales_class = SalesClass.objects.create(sales_team='STATZ')
        cls.nsn = Nsn.objects.create(nsn_code='1111-11-111-1111', description='Widget')
        cls.supplier = Supplier.objects.create(name='Acme Co', cage_code='ACME1')
        cls.packhouse = Supplier.objects.create(name='Packing House', cage_code='PACK1')

    def _awd_payload(self, **overrides):
        payload = {
            'contract_type_kind': 'AWD',
            'contract_number': 'SPE7L1-26-V-TEST',
            'buyer_id': self.buyer.id,
            'sales_class_id': self.sales_class.id,
            'contract_value': Decimal('1000.00'),
            'plan_gross': Decimal('200.00'),
            'award_date': '2026-05-01',
            'due_date': '2026-08-01',
            'clins': [
                {
                    'item_number': '0001',
                    'item_type': 'P',
                    'nsn_id': self.nsn.id,
                    'supplier_id': self.supplier.id,
                    'order_qty': 10,
                    'item_value': Decimal('100.00'),
                    'unit_price': Decimal('100.00'),
                    'quote_value': Decimal('800.00'),
                    'price_per_unit': Decimal('80.00'),
                    'finance_lines': [
                        {'line_type': 'Trucking',
                         'amount_billed': Decimal('50.00'),
                         'description': 'Truck'},
                    ],
                    'splits': [
                        {'company_name': 'STATZ',
                         'split_value': Decimal('150.00'),
                         'split_paid': Decimal('0.00')},
                    ],
                },
            ],
        }
        payload.update(overrides)
        return payload

    def test_awd_happy_path_creates_all_rows(self):
        with transaction.atomic():
            result = create_contract_from_payload(self._awd_payload(), self.user)

        self.assertIsInstance(result.contract, Contract)
        self.assertEqual(result.contract.contract_number, 'SPE7L1-26-V-TEST')
        self.assertEqual(result.contract.buyer_id, self.buyer.id)
        self.assertEqual(result.contract.sales_class_id, self.sales_class.id)
        self.assertEqual(result.contract.status.description, 'Open')

        self.assertEqual(Clin.objects.filter(contract=result.contract).count(), 1)
        clin = result.clins_by_item_number['0001']
        self.assertEqual(clin.item_number, '0001')
        self.assertEqual(clin.nsn_id, self.nsn.id)
        self.assertEqual(clin.supplier_id, self.supplier.id)

        self.assertEqual(ClinSplit.objects.filter(clin=clin).count(), 1)
        self.assertEqual(ContractFinanceLine.objects.filter(clin=clin).count(), 1)

    def test_awd_with_packaging_creates_packaging_row(self):
        payload = self._awd_payload(
            packaging={
                'packhouse_supplier_id': self.packhouse.id,
                'quote_amount': Decimal('75.00'),
                'notes': 'packing notes',
            },
        )
        with transaction.atomic():
            result = create_contract_from_payload(payload, self.user)
        pkg = ContractPackaging.objects.get(contract=result.contract)
        self.assertEqual(pkg.packhouse_id, self.packhouse.id)
        self.assertEqual(pkg.quote_amount, Decimal('75.00'))

    def test_seed_payment_history_creates_initial_rows(self):
        payload = self._awd_payload(seed_payment_history=True)
        with transaction.atomic():
            result = create_contract_from_payload(payload, self.user)

        contract_ct = ContentType.objects.get_for_model(Contract)
        clin_ct = ContentType.objects.get_for_model(Clin)
        contract_phs = PaymentHistory.objects.filter(
            content_type=contract_ct, object_id=result.contract.id,
        )
        clin = result.clins_by_item_number['0001']
        clin_phs = PaymentHistory.objects.filter(
            content_type=clin_ct, object_id=clin.id,
        )
        contract_types = sorted(p.payment_type for p in contract_phs)
        self.assertEqual(contract_types, ['contract_value', 'plan_gross'])
        clin_types = sorted(p.payment_type for p in clin_phs)
        self.assertEqual(clin_types, ['item_value', 'quote_value'])

    def test_awd_missing_buyer_raises(self):
        payload = self._awd_payload(buyer_id=None)
        with self.assertRaises(ContractCreationError) as ctx:
            with transaction.atomic():
                create_contract_from_payload(payload, self.user)
        self.assertIn('buyer', str(ctx.exception).lower())
        # Nothing should have been written.
        self.assertFalse(
            Contract.objects.filter(contract_number='SPE7L1-26-V-TEST').exists()
        )

    def test_awd_clin_missing_nsn_raises(self):
        payload = self._awd_payload()
        payload['clins'][0]['nsn_id'] = None
        with self.assertRaises(ContractCreationError) as ctx:
            with transaction.atomic():
                create_contract_from_payload(payload, self.user)
        self.assertIn('nsn_id', str(ctx.exception))

    def test_do_requires_parent_idiq(self):
        payload = self._awd_payload(contract_type_kind='DO')
        with self.assertRaises(ContractCreationError) as ctx:
            with transaction.atomic():
                create_contract_from_payload(payload, self.user)
        self.assertIn('idiq_contract_id', str(ctx.exception))

    def test_do_with_idiq_links_parent(self):
        parent = IdiqContract.objects.create(contract_number='IDIQ-PARENT')
        payload = self._awd_payload(
            contract_type_kind='DO',
            idiq_contract_id=parent.id,
        )
        with transaction.atomic():
            result = create_contract_from_payload(payload, self.user)
        self.assertEqual(result.contract.idiq_contract_id, parent.id)

    def test_internal_allows_zero_clins(self):
        payload = self._awd_payload(
            contract_type_kind='INTERNAL',
            buyer_id=None,
            clins=[],
            notes='analyst created this internal tracker',
        )
        with transaction.atomic():
            result = create_contract_from_payload(payload, self.user)
        self.assertEqual(
            Clin.objects.filter(contract=result.contract).count(), 0
        )
        note = Note.objects.get(
            content_type=ContentType.objects.get_for_model(Contract),
            object_id=result.contract.id,
        )
        self.assertEqual(note.note_tag, 'intake')

    def test_internal_clin_still_requires_nsn(self):
        payload = self._awd_payload(contract_type_kind='INTERNAL')
        payload['clins'][0]['supplier_id'] = None
        with self.assertRaises(ContractCreationError):
            with transaction.atomic():
                create_contract_from_payload(payload, self.user)

    def test_intake_style_split_computes_value_from_percentage(self):
        # planned_gp = 1000 − (800 + 50) = 150  → percentage 50% → 75.00
        payload = self._awd_payload()
        payload['clins'][0]['item_value'] = Decimal('1000.00')
        payload['clins'][0]['splits'] = [
            {'company_name': 'STATZ', 'percentage': Decimal('50')},
        ]
        with transaction.atomic():
            result = create_contract_from_payload(payload, self.user)
        clin = result.clins_by_item_number['0001']
        split = ClinSplit.objects.get(clin=clin)
        self.assertEqual(split.percentage, Decimal('50'))
        self.assertEqual(split.split_value, Decimal('75.00'))


class IdiqCreationServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='idiq-tester', password='pw')
        cls.buyer = Buyer.objects.create(description='Buying Office')
        cls.nsn1 = Nsn.objects.create(nsn_code='AAA-1', description='A')
        cls.nsn2 = Nsn.objects.create(nsn_code='AAA-2', description='B')
        cls.s1 = Supplier.objects.create(name='S1', cage_code='S1')
        cls.s2 = Supplier.objects.create(name='S2', cage_code='S2')

    def test_idiq_explicit_pairs(self):
        payload = {
            'contract_number': 'IDIQ-EXPLICIT',
            'buyer_id': self.buyer.id,
            'approved_pairs': [
                {
                    'nsn_id': self.nsn1.id,
                    'supplier_id': self.s1.id,
                    'min_order_qty': '10',
                },
                {
                    'nsn_id': self.nsn2.id,
                    'supplier_id': self.s2.id,
                    'min_order_qty': '20',
                },
            ],
        }
        with transaction.atomic():
            idiq = create_idiq_from_payload(payload, self.user)
        details = list(IdiqContractDetails.objects.filter(idiq_contract=idiq))
        self.assertEqual(len(details), 2)

    def test_idiq_requires_contract_number(self):
        with self.assertRaises(ContractCreationError):
            with transaction.atomic():
                create_idiq_from_payload({'contract_number': ''}, self.user)
