from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from contracts.models import (
    Company,
    Contract,
    Clin,
    ClinSplit,
    ContractStatus,
    ContractLevelCharge,
)

class AdjustedGrossTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Test Company', slug='test-company', is_active=True)
        self.status = ContractStatus.objects.create(description='Open')
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number='SPE4A5-25-P-4951',
            status=self.status,
            contract_value=Decimal('10300.00'),
        )
        self.clin1 = Clin.objects.create(
            contract=self.contract,
            item_number='0001',
            item_value=Decimal('250.00'),
            quote_value=Decimal('200.00'),
            order_qty=1.0,
            unit_price=Decimal('250.00'),
        )
        self.clin2 = Clin.objects.create(
            contract=self.contract,
            item_number='0002',
            item_value=Decimal('10050.00'),
            quote_value=Decimal('9000.00'),
            order_qty=1.0,
            unit_price=Decimal('10050.00'),
        )
        self.user = User.objects.create_user(username='finance_user', password='password')

    def test_adjusted_gross_fallback_to_item_value(self):
        # Fallback path (item_value) when wawf_payment is not set
        self.assertEqual(self.clin1.adjusted_gross, Decimal('50.00'))
        self.assertEqual(self.clin2.adjusted_gross, Decimal('1050.00'))
        self.assertEqual(self.contract.adjusted_gross, Decimal('1100.00'))

    def test_adjusted_gross_with_wawf_payment_no_interest(self):
        # Fallback path (item_value) when wawf_payment is equal to item_value
        self.clin1.wawf_payment = Decimal('250.00')
        self.clin1.save()
        self.clin2.wawf_payment = Decimal('10050.00')
        self.clin2.save()
        
        self.assertEqual(self.clin1.adjusted_gross, Decimal('50.00'))
        self.assertEqual(self.clin2.adjusted_gross, Decimal('1050.00'))
        self.assertEqual(self.contract.adjusted_gross, Decimal('1100.00'))

    def test_adjusted_gross_with_interest(self):
        # Test proportional interest additions
        self.clin1.wawf_payment = Decimal('254.21')
        self.clin1.save()
        self.clin2.wawf_payment = Decimal('10219.29')
        self.clin2.save()
        
        self.assertEqual(self.clin1.adjusted_gross, Decimal('54.21'))
        self.assertEqual(self.clin2.adjusted_gross, Decimal('1219.29'))
        self.assertEqual(self.contract.adjusted_gross, Decimal('1273.50'))

    def test_split_recalculation_and_endpoints(self):
        ClinSplit.objects.create(clin=self.clin1, company_name='Company A', percentage=Decimal('50.00'))
        ClinSplit.objects.create(clin=self.clin1, company_name='Company B', percentage=Decimal('50.00'))
        ClinSplit.objects.create(clin=self.clin2, company_name='Company A', percentage=Decimal('50.00'))
        ClinSplit.objects.create(clin=self.clin2, company_name='Company B', percentage=Decimal('50.00'))
        
        # Add interest
        self.clin1.wawf_payment = Decimal('254.21')
        self.clin1.save()
        self.clin2.wawf_payment = Decimal('10219.29')
        self.clin2.save()
        
        # Test split recalculation view logic directly via recalc_splits
        from django.test import RequestFactory
        from contracts.views.split_views import recalc_splits
        
        rf = RequestFactory()
        req = rf.post(reverse('contracts:recalc_splits', kwargs={'contract_pk': self.contract.pk}))
        req.user = self.user
        req.active_company = self.company
        
        response = recalc_splits(req, contract_pk=self.contract.pk)
        self.assertEqual(response.status_code, 200)
        
        # Verify ClinSplit values are updated
        # Total Adj Gross = 1273.50. Company A and Company B should get 50% each: 636.75
        self.clin1.refresh_from_db()
        self.clin2.refresh_from_db()
        
        # Verify splits are distributed proportionally by item_value
        # clin1 (item_value=250.00) vs clin2 (item_value=10050.00)
        # Total Company share = 636.75. clin1 share = 15.46, clin2 share = 621.29
        split_a1 = ClinSplit.objects.get(company_name='Company A', clin=self.clin1)
        split_a2 = ClinSplit.objects.get(company_name='Company A', clin=self.clin2)
        self.assertEqual(split_a1.split_value, Decimal('15.46'))
        self.assertEqual(split_a2.split_value, Decimal('621.29'))

        split_b1 = ClinSplit.objects.get(company_name='Company B', clin=self.clin1)
        split_b2 = ClinSplit.objects.get(company_name='Company B', clin=self.clin2)
        self.assertEqual(split_b1.split_value, Decimal('15.46'))
        self.assertEqual(split_b2.split_value, Decimal('621.29'))

    def test_cia_advance_reduces_adjusted_gross(self):
        # Regression test for SPE7L3-24-P-8222: a CIA advance (action_type='advance')
        # is real cash paid to the supplier and must reduce Contract.adjusted_gross,
        # same as a regular charge. Previously advance rows were excluded from
        # charges_deduction, which overstated adj_gross by the full advance amount.
        base_adj_gross = self.contract.adjusted_gross  # 1100.00 from setUp fallback path
        self.assertEqual(base_adj_gross, Decimal('1100.00'))

        # Unpaid CIA advance (billed_paid_amount not yet set) must NOT reduce adj_gross —
        # estimated_amount is always 0.00 for advance rows.
        cia = ContractLevelCharge.objects.create(
            contract=self.contract,
            label='CIA Advance',
            action_type='advance',
            estimated_amount=Decimal('0.00'),
        )
        self.assertEqual(self.contract.adjusted_gross, Decimal('1100.00'))

        # Once funded, the advance reduces adj_gross exactly like a charge would.
        cia.billed_paid_amount = Decimal('300.00')
        cia.save()
        self.assertEqual(self.contract.adjusted_gross, Decimal('800.00'))

        # A regular charge stacks on top of the advance deduction.
        ContractLevelCharge.objects.create(
            contract=self.contract,
            label='GSI Fee',
            action_type='charge',
            estimated_amount=Decimal('50.00'),
        )
        self.assertEqual(self.contract.adjusted_gross, Decimal('750.00'))
