"""Tests for the inventory spreadsheet sync (parse → preview → apply → export), API and KPI changes."""

import time
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from inventory.api.auth import build_canonical_string, sign_canonical
from inventory.models import InventoryItem, InventorySyncRun
from inventory.selectors import inventory_kpis
from inventory.sync.apply import STALE_MESSAGE, apply_run, create_run
from inventory.sync.banner import sync_banner
from inventory.sync.exporter import build_export
from inventory.sync.parser import SyncFileError, parse_workbook

API_KEY = 'test-inventory-api-key'
HMAC_SECRET = 'test-inventory-hmac-secret'
YELLOW = 'FFFFFF00'
HEADERS = (
    'NSN', 'Description', 'Part Number', 'Manufacturer', 'Quantity',
    'Quantity Remaining', 'Purchase Price', 'Total Cost',
)

# (NSN, Description, Part Number, Manufacturer, Quantity, Qty Remaining, Price, Total Cost, column I)
CORI_ROWS = (
    ('5305-01-111-1111', 'Hex bolt', 'PN-A', 'Acme', 100, None, 2.5, '=E3*G3', None),
    ('5305-01-111-1111', 'Hex bolt', 'PN-A', 'Acme', 50, None, 3.0, 150, None),
    ('6150-01-222-2222', 'Cable lot', 'PN-B', 'Wyandotte', 5000, 200, 1.25, 6250, '*housed at Quality Support'),
    (None, 'Mystery part', 'PN-C', 'Unknown', 3, None, 10, 30, None),
    ('5940-01-333-3333', 'Terminal', 62780.0, 'Amp', 10, None, 0.5, 5, None),
)


def _cori_workbook(rows=CORI_ROWS):
    """Replicates Cori's layout: title row, header row with blank I2, data, blank rows, TOTAL row, PO sheet."""
    from contracts.utils.excel_utils import PatternFill, Workbook

    wb = Workbook()()
    ws = wb.active
    ws.title = 'BulkOrders'
    ws['A1'] = 'Current Inventory'
    for column, title in enumerate(HEADERS, start=1):
        ws.cell(row=2, column=column, value=title)
    row_number = 3
    for row in rows:
        for column, value in enumerate(row, start=1):
            ws.cell(row=row_number, column=column, value=value)
        row_number += 1
    total_row = row_number + 2
    ws.cell(row=total_row, column=7, value='TOTAL ')
    ws.cell(row=total_row, column=8, value=f'=SUM(H3:H{row_number - 1})')

    po = wb.create_sheet('PurchaseOrders')
    po['A1'] = 'PO-1001'
    po['B1'] = 100
    po['C1'] = '=B1*2'
    po['C1'].fill = PatternFill()(fill_type='solid', start_color=YELLOW, end_color=YELLOW)
    return wb


def _bytes(wb):
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _load(data):
    from contracts.utils.excel_utils import load_workbook

    return load_workbook()(BytesIO(data))


def _upload(data, name='Inventory_Tracker.xlsx'):
    return SimpleUploadedFile(
        name, data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


class SyncTestMixin:
    def setUp(self):
        self.user = User.objects.create_user('cori', password='test-pass', first_name='Cori', last_name='Smith')

    def run_for(self, data, name='Inventory_Tracker.xlsx'):
        return create_run(_upload(data, name), self.user)

    def initial_sync(self):
        run = self.run_for(_bytes(_cori_workbook()))
        ok, _ = apply_run(run.id)
        self.assertTrue(ok)
        return run

    def export_wb(self):
        _, data = build_export()
        return _load(data), data

    def assertCounts(self, plan, adds=0, updates=0, removes=0, kept=0):
        self.assertEqual(
            (len(plan['adds']), len(plan['updates']), len(plan['removes']), len(plan['kept'])),
            (adds, updates, removes, kept),
        )


class SyncParseAndPlanTests(SyncTestMixin, TestCase):
    def test_first_sync_into_empty_table(self):
        run = self.run_for(_bytes(_cori_workbook()))
        self.assertEqual(run.status, InventorySyncRun.STATUS_PREVIEW)
        self.assertCounts(run.plan, adds=5)
        self.assertEqual(run.plan['extra_sheets'], ['PurchaseOrders'])
        self.assertIsNone(run.plan['exported_at'])

        ok, _ = apply_run(run.id)
        self.assertTrue(ok)
        self.assertEqual(InventoryItem.objects.count(), 5)
        self.assertEqual(InventoryItem.objects.get(nsn='6150-01-222-2222').itemlocation, 'Quality Support')
        self.assertEqual(InventoryItem.objects.filter(itemlocation='In House').count(), 4)
        lots = InventoryItem.objects.filter(nsn='5305-01-111-1111').order_by('purchaseprice')
        self.assertEqual([(i.quantity, i.purchaseprice) for i in lots], [(100, 2.5), (50, 3.0)])
        self.assertTrue(InventoryItem.objects.filter(nsn='', description='Mystery part').exists())
        self.assertEqual(InventoryItem.objects.get(nsn='5940-01-333-3333').partnumber, '62780')
        self.assertEqual(InventoryItem.objects.get(nsn='6150-01-222-2222').quantity_remaining, 200)

    def test_first_sync_matches_existing_rows_by_key(self):
        InventoryItem.objects.create(
            nsn='5305-01-111-1111', description='Hex bolt', partnumber='pn-a', manufacturer='Acme',
            itemlocation='In House', quantity=90, purchaseprice=2.5,
        )
        InventoryItem.objects.create(
            nsn='5305-01-111-1111', description='Hex bolt', partnumber='PN-A', manufacturer='Acme',
            itemlocation='In House', quantity=50, purchaseprice=3.0,
        )
        run = self.run_for(_bytes(_cori_workbook()))
        self.assertCounts(run.plan, adds=3, updates=1)
        self.assertEqual(run.plan['unchanged_count'], 1)
        self.assertEqual(run.plan['updates'][0]['changes'], {'partnumber': ['pn-a', 'PN-A'], 'quantity': [90, 100]})
        apply_run(run.id)
        self.assertEqual(InventoryItem.objects.count(), 5)
        self.assertEqual(InventoryItem.objects.filter(nsn='5305-01-111-1111').count(), 2)

    def test_round_trip_export_is_a_no_op(self):
        self.initial_sync()
        _, data = build_export()
        parsed = parse_workbook(data)
        self.assertIsNotNone(parsed.exported_at)
        self.assertEqual(parsed.errors, [])
        run = self.run_for(data)
        self.assertCounts(run.plan)
        self.assertEqual(run.plan['unchanged_count'], 5)
        self.assertEqual(run.plan['exported_at'], parsed.exported_at.isoformat())
        self.assertEqual(run.warnings, [])

    def test_edit_delete_and_add_in_exported_file(self):
        self.initial_sync()
        wb, _ = self.export_wb()
        ws = wb['BulkOrders']
        ws['E3'] = 99
        removed_id = ws['J4'].value
        ws.delete_rows(4)
        new_row = 7
        for column, value in enumerate(('7010-01-444-4444', 'New laptop', 'LT-1', 'Dell', 2, None, 900), start=1):
            ws.cell(row=new_row, column=column, value=value)
        run = self.run_for(_bytes(wb))
        self.assertCounts(run.plan, adds=1, updates=1, removes=1)
        self.assertEqual(run.plan['updates'][0]['changes'], {'quantity': [100, 99]})
        self.assertEqual(run.plan['removes'][0]['id'], removed_id)
        self.assertEqual(run.plan['adds'][0]['nsn'], '7010-01-444-4444')

    def test_items_added_on_page_after_download_are_kept(self):
        self.initial_sync()
        _, data = build_export()
        page_item = InventoryItem.objects.create(nsn='8888-00-000-0001', description='Added on page', quantity=1)
        run = self.run_for(data)
        self.assertCounts(run.plan, kept=1)
        self.assertEqual(run.plan['kept'][0]['id'], page_item.id)
        ok, _ = apply_run(run.id)
        self.assertTrue(ok)
        self.assertTrue(InventoryItem.objects.filter(pk=page_item.id).exists())

        unstamped = self.run_for(_bytes(_cori_workbook()))
        self.assertCounts(unstamped.plan, removes=1)
        self.assertEqual(unstamped.plan['removes'][0]['id'], page_item.id)

    def test_duplicate_statz_id_becomes_add_with_warning(self):
        self.initial_sync()
        wb, _ = self.export_wb()
        ws = wb['BulkOrders']
        for column, value in enumerate(('1111-00-000-0001', 'Copy', 'CP-1', 'Acme', 1, None, 1), start=1):
            ws.cell(row=8, column=column, value=value)
        ws.cell(row=8, column=10, value=ws['J3'].value)
        run = self.run_for(_bytes(wb))
        self.assertCounts(run.plan, adds=1)
        self.assertEqual(run.warnings, [
            f"Row 8 repeats STATZ ID {ws['J3'].value} from row 3; it will be added as a new item.",
        ])

    def test_unknown_statz_id_becomes_add_with_warning(self):
        self.initial_sync()
        wb, _ = self.export_wb()
        ws = wb['BulkOrders']
        for column, value in enumerate(('1111-00-000-0002', 'Ghost', 'GH-1', 'Acme', 1, None, 1), start=1):
            ws.cell(row=8, column=column, value=value)
        ws.cell(row=8, column=10, value=999999)
        run = self.run_for(_bytes(wb))
        self.assertCounts(run.plan, adds=1)
        self.assertEqual(run.warnings, [
            'Row 8 was deleted in STATZWeb after this file was downloaded; it will be added again.',
        ])

    def test_bad_values_fail_the_run_with_row_numbers(self):
        rows = (
            ('1111-00-000-0003', 'Negative', 'N-1', 'Acme', -5, None, 1, None, None),
            ('1111-00-000-0004', 'Bad price', 'B-1', 'Acme', 1, None, 'abc', None, None),
            ('1111-00-000-0005', 'Formula', 'F-1', 'Acme', '=77-60', None, 1, None, None),
        )
        run = self.run_for(_bytes(_cori_workbook(rows)))
        self.assertEqual(run.status, InventorySyncRun.STATUS_FAILED)
        self.assertEqual(len(run.errors), 3)
        self.assertTrue(run.errors[0].startswith('Row 3: Quantity must be a whole number'))
        self.assertTrue(run.errors[1].startswith('Row 4: Purchase Price must be a number'))
        self.assertEqual(
            run.errors[2],
            "Row 5: Quantity is a formula Excel hasn't calculated. Open the file in Excel, save it, and upload again.",
        )
        ok, message = apply_run(run.id)
        self.assertFalse(ok)
        self.assertEqual(message, STALE_MESSAGE)
        self.assertEqual(InventoryItem.objects.count(), 0)

    def test_non_xlsx_and_oversize_uploads_rejected(self):
        with self.assertRaisesMessage(SyncFileError, '.xlsx'):
            self.run_for(b'\xd0\xcf\x11\xe0', name='Inventory_Tracker.xls')
        with self.assertRaisesMessage(SyncFileError, '5 MB'):
            self.run_for(b'PK' + b'0' * (5 * 1024 * 1024), name='big.xlsx')
        with self.assertRaises(SyncFileError):
            self.run_for(b'not a zip', name='fake.xlsx')
        self.assertEqual(InventorySyncRun.objects.count(), 0)

    def test_new_upload_discards_older_previews(self):
        first = self.run_for(_bytes(_cori_workbook()))
        self.run_for(_bytes(_cori_workbook()))
        first.refresh_from_db()
        self.assertEqual(first.status, InventorySyncRun.STATUS_DISCARDED)


class SyncApplyTests(SyncTestMixin, TestCase):
    def test_apply_refused_when_item_changed_after_preview(self):
        self.initial_sync()
        run = self.run_for(_bytes(_cori_workbook()))
        item = InventoryItem.objects.first()
        item.description = 'Edited after preview'
        item.save()
        ok, message = apply_run(run.id)
        self.assertFalse(ok)
        self.assertEqual(message, STALE_MESSAGE)
        run.refresh_from_db()
        self.assertEqual(run.status, InventorySyncRun.STATUS_DISCARDED)

    def test_apply_refused_for_non_preview_run(self):
        run = self.initial_sync()
        ok, message = apply_run(run.id)
        self.assertFalse(ok)
        self.assertEqual(message, STALE_MESSAGE)
        run.refresh_from_db()
        self.assertEqual(run.status, InventorySyncRun.STATUS_APPLIED)
        self.assertEqual(InventoryItem.objects.count(), 5)

    def test_large_removal_requires_checkbox_server_side(self):
        for n in range(8):
            InventoryItem.objects.create(nsn=f'9999-00-000-00{n:02d}', description='Old', quantity=1)
        self.client.force_login(self.user)
        run = self.run_for(_bytes(_cori_workbook()))
        self.assertEqual(len(run.plan['removes']), 8)
        resp = self.client.post(reverse('inventory:sync_apply', args=[run.id]), follow=True)
        self.assertContains(resp, STALE_MESSAGE)
        run.refresh_from_db()
        self.assertEqual(run.status, InventorySyncRun.STATUS_DISCARDED)
        self.assertEqual(InventoryItem.objects.count(), 8)

        run = self.run_for(_bytes(_cori_workbook()))
        preview = self.client.get(reverse('inventory:sync_preview', args=[run.id]))
        self.assertContains(preview, 'I understand 8 items will be removed.')
        self.client.post(reverse('inventory:sync_apply', args=[run.id]), {'acknowledge_removals': '1'})
        run.refresh_from_db()
        self.assertEqual(run.status, InventorySyncRun.STATUS_APPLIED)
        self.assertEqual(InventoryItem.objects.count(), 5)

    def test_is_public_preserved_and_new_items_private(self):
        self.initial_sync()
        _, data = build_export()
        wb = _load(data)
        item = InventoryItem.objects.get(pk=wb['BulkOrders']['J3'].value)
        item.is_public = True
        item.save()
        ws = wb['BulkOrders']
        ws['E3'] = 1
        for column, value in enumerate(('2222-00-000-0001', 'Brand new', 'BN-1', 'Acme', 4, None, 2), start=1):
            ws.cell(row=8, column=column, value=value)
        run = self.run_for(_bytes(wb))
        self.assertTrue(run.plan['updates'][0]['conflict'])
        ok, _ = apply_run(run.id)
        self.assertTrue(ok)
        item.refresh_from_db()
        self.assertTrue(item.is_public)
        self.assertEqual(item.quantity, 1)
        self.assertFalse(InventoryItem.objects.get(nsn='2222-00-000-0001').is_public)

    def test_apply_uses_save_for_totalcost_and_last_modified(self):
        self.initial_sync()
        added = InventoryItem.objects.get(nsn='6150-01-222-2222')
        self.assertEqual(added.totalcost, 6250.0)
        self.assertIsNotNone(added.last_modified)
        before = added.last_modified

        wb, _ = self.export_wb()
        ws = wb['BulkOrders']
        row = next(r for r in range(3, 8) if ws.cell(row=r, column=10).value == added.id)
        ws.cell(row=row, column=5, value=10)
        run = self.run_for(_bytes(wb))
        apply_run(run.id)
        added.refresh_from_db()
        self.assertEqual(added.totalcost, 12.5)
        self.assertGreater(added.last_modified, before)


class SyncExportTests(SyncTestMixin, TestCase):
    def test_export_layout_and_carried_sheets(self):
        self.initial_sync()
        filename, data = build_export()
        self.assertRegex(filename, r'^Inventory_Tracker_\d{4}-\d{2}-\d{2}\.xlsx$')
        wb = _load(data)
        self.assertEqual(wb.sheetnames, ['BulkOrders', 'PurchaseOrders'])
        self.assertEqual(wb.properties.creator, 'STATZWeb')
        ws = wb['BulkOrders']
        self.assertEqual(ws['A1'].value, 'Current Inventory')
        self.assertEqual(ws['J1'].value, 'STATZ Export')
        self.assertIsNotNone(parse_workbook(data).exported_at)
        self.assertTrue(ws.column_dimensions['J'].hidden)
        self.assertTrue(ws.column_dimensions['K'].hidden)
        self.assertEqual(ws.freeze_panes, 'A3')
        self.assertEqual(ws.auto_filter.ref, 'A2:I7')
        self.assertEqual(ws['I2'].value, 'Location')
        self.assertEqual(ws['H3'].value, '=IF(OR(E3="",G3=""),"",E3*G3)')
        self.assertEqual(ws['G9'].value, 'TOTAL')
        self.assertEqual(ws['H9'].value, '=SUM(H3:H7)')
        self.assertEqual(ws['G10'].value, 'ON-HAND VALUE')
        self.assertEqual(
            ws['H10'].value,
            '=SUMPRODUCT((F3:F7="")*E3:E7*G3:G7)+SUMPRODUCT((F3:F7<>"")*F3:F7*G3:G7)',
        )
        self.assertEqual(ws['A2'].fill.fgColor.rgb, 'FF000000')
        self.assertTrue(ws['A2'].font.bold)
        self.assertEqual(ws['B3'].font.name, 'Aptos Narrow')
        po = wb['PurchaseOrders']
        self.assertEqual(po['C1'].value, '=B1*2')
        self.assertEqual(po['C1'].fill.fgColor.rgb, YELLOW)
        self.assertEqual(po['B1'].value, 100)

    def test_export_view_downloads_xlsx(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('inventory:sync_export'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment; filename="Inventory_Tracker_', resp['Content-Disposition'])
        self.assertEqual(_load(resp.content).sheetnames, ['BulkOrders'])


@override_settings(INVENTORY_API_KEY=API_KEY, INVENTORY_API_HMAC_SECRET=HMAC_SECRET)
class SyncApiTests(TestCase):
    def _get(self, path, params=None):
        ts = str(int(time.time()))
        signature = sign_canonical(HMAC_SECRET, build_canonical_string('GET', path, ts, b''))
        return self.client.get(path, params or {}, HTTP_X_API_KEY=API_KEY, HTTP_X_TIMESTAMP=ts, HTTP_X_SIGNATURE=signature)

    def test_quantity_in_stock_and_order(self):
        drawn_down = InventoryItem.objects.create(nsn='B-NSN', quantity=5000, quantity_remaining=0, is_public=True)
        blank = InventoryItem.objects.create(nsn='', quantity=5, is_public=True)
        lot_one = InventoryItem.objects.create(nsn='A-NSN', quantity=10, is_public=True)
        lot_two = InventoryItem.objects.create(nsn='A-NSN', quantity=20, quantity_remaining=7, is_public=True)
        path = reverse('inventory_api:item_list')

        results = self._get(path).json()['results']
        self.assertEqual([r['id'] for r in results], [lot_one.id, lot_two.id, drawn_down.id, blank.id])
        quantities = {r['id']: r['quantity'] for r in results}
        self.assertEqual(quantities[lot_two.id], 7)
        self.assertEqual(quantities[drawn_down.id], 0)
        self.assertEqual(set(results[0]), {'id', 'nsn', 'description', 'part_number', 'manufacturer', 'quantity'})

        in_stock = {r['id'] for r in self._get(path, {'in_stock': 'true'}).json()['results']}
        self.assertEqual(in_stock, {lot_one.id, lot_two.id, blank.id})


@override_settings(REQUIRE_LOGIN=True)
class SyncPageTests(SyncTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_on_hand_value_kpi(self):
        InventoryItem.objects.create(nsn='X', quantity=5000, quantity_remaining=0, purchaseprice=5.0)
        InventoryItem.objects.create(nsn='Y', quantity=10, purchaseprice=2.0)
        self.assertAlmostEqual(inventory_kpis()['on_hand_value'], 20.0)
        resp = self.client.get(reverse('inventory:dashboard'))
        self.assertAlmostEqual(resp.context['kpis']['on_hand_value'], 20.0)
        self.assertEqual(resp.context['kpis']['on_hand_units'], 10)
        self.assertContains(resp, 'On-Hand Value')
        self.assertContains(resp, '$20.00')

    def test_sync_banner_on_dashboard_and_form(self):
        item = InventoryItem.objects.create(nsn='Z', quantity=1)
        run = InventorySyncRun.objects.create(
            created_by=self.user, file_bytes=b'', status=InventorySyncRun.STATUS_APPLIED, applied_at=timezone.now(),
        )
        banner_text = 'Inventory is synced from Cori Smith'
        self.assertContains(self.client.get(reverse('inventory:dashboard')), banner_text)
        self.assertContains(self.client.get(reverse('inventory:edit_item', args=[item.id])), banner_text)
        self.assertContains(self.client.get(reverse('inventory:add_item')), banner_text)

        InventorySyncRun.objects.filter(pk=run.pk).update(applied_at=timezone.now() - timedelta(days=61))
        self.assertIsNone(sync_banner())
        self.assertNotContains(self.client.get(reverse('inventory:dashboard')), 'Inventory is synced from')
        self.assertNotContains(self.client.get(reverse('inventory:add_item')), 'Inventory is synced from')

    def test_upload_view_redirects_to_preview(self):
        resp = self.client.post(reverse('inventory:sync_upload'), {'workbook': _upload(_bytes(_cori_workbook()))})
        run = InventorySyncRun.objects.get()
        self.assertRedirects(resp, reverse('inventory:sync_preview', args=[run.id]))
        preview = self.client.get(resp.url)
        self.assertContains(preview, 'Spreadsheet Sync')
        self.assertContains(preview, 'Apply changes')
        self.assertContains(preview, 'Quality Support')

    def test_upload_view_rejects_xls(self):
        resp = self.client.post(
            reverse('inventory:sync_upload'), {'workbook': _upload(b'xx', name='old.xls')}, follow=True,
        )
        self.assertContains(resp, 'Only Excel .xlsx files can be uploaded.')
        self.assertEqual(InventorySyncRun.objects.count(), 0)

    def test_failed_run_shows_errors_only(self):
        rows = (('1111-00-000-0003', 'Negative', 'N-1', 'Acme', -5, None, 1, None, None),)
        run = self.run_for(_bytes(_cori_workbook(rows)))
        resp = self.client.get(reverse('inventory:sync_preview', args=[run.id]))
        self.assertContains(resp, 'Row 3: Quantity must be a whole number')
        self.assertContains(resp, 'Upload a corrected file')
        self.assertNotContains(resp, 'Apply changes')

    def test_apply_view_then_sync_complete(self):
        run = self.run_for(_bytes(_cori_workbook()))
        resp = self.client.post(reverse('inventory:sync_apply', args=[run.id]), follow=True)
        self.assertContains(resp, 'Sync complete')
        self.assertContains(resp, 'Download updated spreadsheet')

    def test_discard_view_and_get_not_allowed(self):
        run = self.run_for(_bytes(_cori_workbook()))
        self.assertEqual(self.client.get(reverse('inventory:sync_discard', args=[run.id])).status_code, 405)
        self.client.post(reverse('inventory:sync_discard', args=[run.id]))
        run.refresh_from_db()
        self.assertEqual(run.status, InventorySyncRun.STATUS_DISCARDED)

    def test_sync_home_lists_runs(self):
        self.run_for(_bytes(_cori_workbook()), name='Cori.xlsx')
        resp = self.client.get(reverse('inventory:sync_home'))
        self.assertContains(resp, 'Cori.xlsx')
        self.assertContains(resp, 'Recent syncs')

    def test_qty_remaining_form_validation(self):
        resp = self.client.post(reverse('inventory:add_item'), {'nsn': 'neg-rem', 'quantity_remaining': '-1'})
        self.assertContains(resp, 'Qty remaining cannot be negative.')
        self.assertContains(resp, 'For bulk lots drawn down over time.')


@override_settings(REQUIRE_LOGIN=True)
class SyncAccessTests(TestCase):
    def test_anonymous_sync_home_redirects_to_login(self):
        resp = self.client.get(reverse('inventory:sync_home'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('users:login'), resp.url)
