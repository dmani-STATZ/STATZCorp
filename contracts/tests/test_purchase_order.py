import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from contracts.models import Company, Contract, Clin, PurchaseOrder, POLineItem
from suppliers.models import Supplier
from users.models import UserCompanyMembership


def _create_company(name='Test Co', enable_po_generator=True):
    return Company.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        is_active=True,
        enable_po_generator=enable_po_generator
    )


def _create_user(username='tester', password='testpw12345', company=None):
    user = User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password=password,
    )
    if company is not None:
        UserCompanyMembership.objects.create(user=user, company=company, is_default=True)
    return user


def _create_contract(company, contract_number='C-0001', po_number='P-0001'):
    return Contract.objects.create(
        contract_number=contract_number,
        po_number=po_number,
        company=company,
    )


def _create_clin(contract, item_number='0001', order_qty=Decimal('10'), price_per_unit=Decimal('5.50'), quote_value=Decimal('55.00'), supplier=None):
    return Clin.objects.create(
        contract=contract,
        item_number=item_number,
        order_qty=order_qty,
        price_per_unit=price_per_unit,
        quote_value=quote_value,
        supplier=supplier
    )


class PurchaseOrderViewsTests(TestCase):
    def setUp(self):
        self.company = _create_company('Test Company', enable_po_generator=True)
        self.user = _create_user('po_tester', company=self.company)
        
        self.client = Client()
        self.client.login(username='po_tester', password='testpw12345')
        
        session = self.client.session
        session['active_company_id'] = self.company.id
        session.save()
        
        self.supplier = Supplier.objects.create(name='Supplier A', cage_code='12345')
        self.contract = _create_contract(self.company, 'DLA-2026-01', 'PO-123')
        self.clin1 = _create_clin(self.contract, '0001', Decimal('100'), Decimal('1.50'), supplier=self.supplier)
        self.clin2 = _create_clin(self.contract, '0002', Decimal('200'), Decimal('2.00'), supplier=self.supplier)

    def test_po_page_gating_disabled(self):
        # Disable PO generator for the company
        self.company.enable_po_generator = False
        self.company.save()
        
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_po_page_gating_enabled(self):
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'contracts/purchase_order_page.html')

    def test_po_creation_and_seeding(self):
        # Verify no PO exists initially
        self.assertFalse(PurchaseOrder.objects.filter(contract=self.contract).exists())
        
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        response = self.client.get(url)
        
        # Verify PO is created
        self.assertTrue(PurchaseOrder.objects.filter(contract=self.contract).exists())
        po = PurchaseOrder.objects.get(contract=self.contract)
        self.assertEqual(po.po_number, 'PO-123')
        self.assertEqual(po.supplier, self.supplier)
        
        # Verify line items are seeded
        lines = po.line_items.all().order_by('sort_order')
        self.assertEqual(lines.count(), 2)
        self.assertEqual(lines[0].qty, Decimal('100.0000'))
        self.assertEqual(lines[0].rate, Decimal('1.5000'))
        self.assertEqual(lines[0].amount, Decimal('150.00'))
        self.assertEqual(lines[1].qty, Decimal('200.0000'))
        self.assertEqual(lines[1].rate, Decimal('2.0000'))
        self.assertEqual(lines[1].amount, Decimal('400.00'))

    def test_po_seeding_is_once_only(self):
        # Trigger creation & seeding
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        self.client.get(url)
        
        po = PurchaseOrder.objects.get(contract=self.contract)
        initial_line_count = po.line_items.count()
        self.assertEqual(initial_line_count, 2)
        
        # Add a custom line manually
        POLineItem.objects.create(purchase_order=po, sort_order=3, activity='Custom line')
        
        # Re-fetch page
        self.client.get(url)
        
        # Verify lines are NOT re-seeded/duplicated
        self.assertEqual(po.line_items.count(), 3)

    def test_update_purchase_order(self):
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        self.client.get(url)
        po = PurchaseOrder.objects.get(contract=self.contract)
        
        update_url = reverse('contracts:purchase-order-update', args=[po.id])
        post_data = {
            'po_number': 'PO-999-REV',
            'po_date': '2026-06-30',
            'footer': 'New PO Footer Text',
            'supplier_id': self.supplier.id
        }
        response = self.client.post(update_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})
        
        po.refresh_from_db()
        self.assertEqual(po.po_number, 'PO-999-REV')
        self.assertEqual(str(po.po_date), '2026-06-30')
        self.assertEqual(po.footer, 'New PO Footer Text')

    def test_add_po_line(self):
        # Create PO first
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        self.client.get(url)
        po = PurchaseOrder.objects.get(contract=self.contract)
        
        add_url = reverse('contracts:po-line-add', args=[po.id])
        post_data = {
            'activity': 'New dynamic text line',
            'qty': '50',
            'rate': '2.50',
            'amount': '125.00'
        }
        response = self.client.post(add_url, post_data)
        self.assertEqual(response.status_code, 200)
        
        res_json = response.json()
        self.assertTrue(res_json['success'])
        self.assertEqual(res_json['line']['activity'], 'New dynamic text line')
        self.assertEqual(Decimal(res_json['line']['qty']), Decimal('50'))
        self.assertEqual(Decimal(res_json['line']['rate']), Decimal('2.50'))
        self.assertEqual(Decimal(res_json['line']['amount']), Decimal('125.00'))
        
        self.assertEqual(po.line_items.count(), 3)

    def test_update_po_line(self):
        # Create PO first
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        self.client.get(url)
        po = PurchaseOrder.objects.get(contract=self.contract)
        line = po.line_items.first()
        
        update_url = reverse('contracts:po-line-update', args=[line.id])
        post_data = {
            'activity': 'Updated Line Description',
            'qty': '10',
            'rate': '15.00',
            'amount': '150.00'
        }
        response = self.client.post(update_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})
        
        line.refresh_from_db()
        self.assertEqual(line.activity, 'Updated Line Description')
        self.assertEqual(line.qty, Decimal('10.0000'))
        self.assertEqual(line.rate, Decimal('15.0000'))
        self.assertEqual(line.amount, Decimal('150.00'))

    def test_delete_po_line(self):
        # Create PO first
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        self.client.get(url)
        po = PurchaseOrder.objects.get(contract=self.contract)
        line = po.line_items.first()
        
        delete_url = reverse('contracts:po-line-delete', args=[line.id])
        response = self.client.post(delete_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})
        
        self.assertEqual(po.line_items.count(), 1)

    def test_reorder_po_lines(self):
        # Create PO first
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        self.client.get(url)
        po = PurchaseOrder.objects.get(contract=self.contract)
        lines = list(po.line_items.all().order_by('sort_order'))
        
        # Swap their positions
        ordered_ids = [lines[1].id, lines[0].id]
        
        reorder_url = reverse('contracts:po-lines-reorder', args=[po.id])
        response = self.client.post(
            reorder_url,
            data=json.dumps({'ordered_ids': ordered_ids}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})
        
        lines[0].refresh_from_db()
        lines[1].refresh_from_db()
        self.assertEqual(lines[0].sort_order, 2)
        self.assertEqual(lines[1].sort_order, 1)

    def test_po_print_view(self):
        # Create PO first
        url = reverse('contracts:purchase-order-page', args=[self.contract.id])
        self.client.get(url)
        po = PurchaseOrder.objects.get(contract=self.contract)
        
        # Test GET print view
        print_url = reverse('contracts:purchase-order-print', args=[po.id])
        response = self.client.get(print_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'contracts/po_print.html')
        
        # Verify context details
        self.assertEqual(response.context['po'], po)
        self.assertEqual(response.context['total'], Decimal('550.00'))

