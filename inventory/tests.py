"""Tests for the inventory dashboard, model, form, and the public inventory API."""

import time

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from inventory.api.auth import build_canonical_string, sign_canonical
from inventory.forms import InventoryItemForm
from inventory.models import InventoryItem

API_KEY = 'test-inventory-api-key'
HMAC_SECRET = 'test-inventory-hmac-secret'
PUBLIC_KEYS = {'id', 'nsn', 'description', 'part_number', 'manufacturer', 'quantity'}


def _item(**kwargs):
    defaults = {
        'nsn': '5305-01-234-5678',
        'description': 'Widget',
        'partnumber': 'PN-1',
        'manufacturer': 'Acme',
        'itemlocation': 'Shelf A',
        'quantity': 5,
        'purchaseprice': 2.5,
        'is_public': False,
    }
    defaults.update(kwargs)
    return InventoryItem.objects.create(**defaults)


@override_settings(INVENTORY_API_KEY=API_KEY, INVENTORY_API_HMAC_SECRET=HMAC_SECRET)
class InventoryAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.list_path = reverse('inventory_api:item_list')
        self.public = _item(nsn='5305-01-234-5678', description='Hex bolt', is_public=True)
        self.public_empty = _item(
            nsn=None, description=None, partnumber=None, manufacturer='Bolt Co',
            quantity=None, purchaseprice=None, is_public=True,
        )
        self.private = _item(nsn='1111-11-111-1111', description='Secret thing', is_public=False)

    def _headers(self, method, path, timestamp=None, key=API_KEY, secret=HMAC_SECRET):
        timestamp = timestamp or str(int(time.time()))
        signature = sign_canonical(secret, build_canonical_string(method, path, timestamp, b''))
        return {
            'HTTP_X_API_KEY': key,
            'HTTP_X_TIMESTAMP': timestamp,
            'HTTP_X_SIGNATURE': signature,
        }

    def _get(self, path, params=None, **header_kwargs):
        return self.client.get(path, params or {}, **self._headers('GET', path, **header_kwargs))

    def _ids(self, response):
        return {row['id'] for row in response.json()['results']}

    def test_list_returns_only_public_rows(self):
        resp = self._get(self.list_path)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Cache-Control'], 'no-store')
        self.assertEqual(self._ids(resp), {self.public.id, self.public_empty.id})
        self.assertEqual(resp.json()['count'], 2)

    def test_result_keys_are_allowlisted(self):
        resp = self._get(self.list_path)
        for row in resp.json()['results']:
            self.assertEqual(set(row), PUBLIC_KEYS)
        text = resp.content.decode().lower()
        for forbidden in ('purchaseprice', 'totalcost', 'itemlocation', 'shelf a'):
            self.assertNotIn(forbidden, text)

    def test_null_values_serialize_as_defaults(self):
        resp = self._get(reverse('inventory_api:item_detail', args=[self.public_empty.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['nsn'], '')
        self.assertEqual(body['description'], '')
        self.assertEqual(body['part_number'], '')
        self.assertEqual(body['quantity'], 0)

    def test_auth_failures_share_status_and_body(self):
        ts = str(int(time.time()))
        good = self._headers('GET', self.list_path, timestamp=ts)
        missing_key = {k: v for k, v in good.items() if k != 'HTTP_X_API_KEY'}
        wrong_key = {**good, 'HTTP_X_API_KEY': 'nope'}
        bad_sig = {**good, 'HTTP_X_SIGNATURE': '0' * 64}
        stale = self._headers('GET', self.list_path, timestamp=str(int(time.time()) - 600))
        bodies = []
        for headers in (missing_key, wrong_key, bad_sig, stale):
            resp = self.client.get(self.list_path, **headers)
            self.assertEqual(resp.status_code, 401)
            self.assertEqual(resp.json()['error']['code'], 'unauthorized')
            bodies.append(resp.content)
        self.assertEqual(len(set(bodies)), 1)

    def test_unset_secrets_fail_closed(self):
        for overrides in (
            {'INVENTORY_API_KEY': ''},
            {'INVENTORY_API_HMAC_SECRET': ''},
        ):
            with self.subTest(overrides=overrides), self.settings(**overrides):
                resp = self._get(self.list_path)
                self.assertEqual(resp.status_code, 401)
                self.assertEqual(resp.json()['error']['code'], 'unauthorized')

    def test_non_get_returns_405_after_auth(self):
        resp = self.client.post(self.list_path, **self._headers('POST', self.list_path))
        self.assertEqual(resp.status_code, 405)
        unsigned = self.client.post(self.list_path)
        self.assertEqual(unsigned.status_code, 401)

    def test_detail_non_public_and_missing_return_404(self):
        for pk in (self.private.id, 999999):
            resp = self._get(reverse('inventory_api:item_detail', args=[pk]))
            self.assertEqual(resp.status_code, 404)
            self.assertEqual(resp.json(), {'error': 'not_found'})

    def test_page_size_clamped_and_invalid_params_rejected(self):
        resp = self._get(self.list_path, {'page_size': '5000'})
        self.assertEqual(resp.json()['page_size'], 200)
        for params in ({'page': 'abc'}, {'page_size': 'x'}, {'page': '0'}):
            resp = self._get(self.list_path, params)
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json(), {'error': 'invalid_parameter'})

    def test_filters(self):
        self.assertEqual(self._ids(self._get(self.list_path, {'q': 'hex'})), {self.public.id})
        self.assertEqual(self._ids(self._get(self.list_path, {'q': 'shelf'})), set())
        self.assertEqual(self._ids(self._get(self.list_path, {'q': 'secret'})), set())
        self.assertEqual(
            self._ids(self._get(self.list_path, {'nsn': '5305012345678'})), {self.public.id}
        )
        self.assertEqual(
            self._ids(self._get(self.list_path, {'in_stock': 'true'})), {self.public.id}
        )


@override_settings(
    REQUIRE_LOGIN=True,
    INVENTORY_API_KEY=API_KEY,
    INVENTORY_API_HMAC_SECRET=HMAC_SECRET,
)
class InventoryAccessTests(TestCase):
    def test_anonymous_dashboard_redirects_to_login(self):
        resp = self.client.get(reverse('inventory:dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('users:login'), resp.url)

    def test_unsigned_api_request_is_401_not_login_redirect(self):
        resp = self.client.get(reverse('inventory_api:item_list'))
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error']['code'], 'unauthorized')

    def test_anonymous_autocomplete_redirects_to_login(self):
        resp = self.client.get(reverse('inventory:autocomplete_nsn'), {'term': '5'})
        self.assertEqual(resp.status_code, 302)


@override_settings(REQUIRE_LOGIN=True)
class InventoryDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('inv_user', password='test-pass')
        self.client.force_login(self.user)
        self.url = reverse('inventory:dashboard')
        self.b = _item(nsn='B', quantity=2, purchaseprice=10.0, is_public=True)
        self.a = _item(nsn='A', quantity=None, purchaseprice=5.0)

    def test_dashboard_renders_with_kpis(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        kpis = resp.context['kpis']
        self.assertEqual(kpis['item_count'], 2)
        self.assertEqual(kpis['on_hand_units'], 2)
        self.assertAlmostEqual(kpis['on_hand_value'], 20.0)
        self.assertEqual(kpis['public_count'], 1)

    def test_hostile_sort_falls_back_to_default(self):
        resp = self.client.get(self.url, {'sort': 'id; DROP TABLE x', 'dir': 'sideways'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([i.id for i in resp.context['items']], sorted([self.a.id, self.b.id]))

    def test_whitelisted_sort_applies(self):
        resp = self.client.get(self.url, {'sort': 'nsn', 'dir': 'asc'})
        self.assertEqual([i.nsn for i in resp.context['items']], ['A', 'B'])

    def test_invalid_page_yields_first_page(self):
        resp = self.client.get(self.url, {'page': 'abc'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['page_obj'].number, 1)

    def test_visibility_filter(self):
        resp = self.client.get(self.url, {'vis': 'public'})
        self.assertEqual([i.id for i in resp.context['items']], [self.b.id])

    def test_sort_links_preserve_query_params(self):
        resp = self.client.get(self.url, {'q': 'B', 'vis': 'public', 'per_page': '50'})
        self.assertContains(resp, 'q=B&amp;vis=public&amp;per_page=50&amp;sort=nsn&amp;dir=asc')
        self.assertContains(resp, 'inventory/js/inventory_dashboard.js')

    def test_item_form_renders_public_checkbox(self):
        resp = self.client.get(reverse('inventory:edit_item', args=[self.b.id]))
        self.assertContains(resp, 'Show on public website')
        self.assertContains(resp, 'name="is_public"')
        self.assertContains(resp, 'checked')


class InventoryModelFormTests(TestCase):
    def test_save_with_null_inputs_sets_totalcost_none(self):
        no_qty = _item(quantity=None, purchaseprice=3.0)
        no_price = _item(quantity=4, purchaseprice=None)
        self.assertIsNone(no_qty.totalcost)
        self.assertIsNone(no_price.totalcost)
        both = _item(quantity=4, purchaseprice=3.0)
        self.assertEqual(both.totalcost, 12.0)

    def test_str_is_bound_to_model(self):
        self.assertEqual(str(_item(nsn='5305-01-234-5678')), '5305-01-234-5678')

    def test_negative_values_are_rejected(self):
        form = InventoryItemForm(data={'quantity': '-1', 'purchaseprice': '-0.01'})
        self.assertFalse(form.is_valid())
        self.assertIn('Quantity cannot be negative.', form.errors['quantity'])
        self.assertIn('Unit price cannot be negative.', form.errors['purchaseprice'])

    def test_form_saves_is_public(self):
        form = InventoryItemForm(data={'nsn': '5305-01-234-5678', 'quantity': '1', 'is_public': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        item.refresh_from_db()
        self.assertTrue(item.is_public)
        self.assertEqual(form.fields['is_public'].label, 'Show on public website')
        self.assertEqual(form.fields['nsn'].widget.attrs['class'], 'form-control autocomplete-nsn')
        self.assertEqual(form.fields['is_public'].widget.attrs['class'], 'form-check-input')
        self.assertNotIn('placeholder', form.fields['description'].widget.attrs)


@override_settings(REQUIRE_LOGIN=True)
class InventoryItemFormViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('form_user', password='test-pass')
        self.client.force_login(self.user)
        self.add_url = reverse('inventory:add_item')
        self.item = _item(nsn='5305-01-234-5678', description='Hex bolt', quantity=4, purchaseprice=2.5)

    def _content_block(self, response):
        """The form body plus its external script, excluding the base template's own scripts."""
        html = response.content.decode()
        start = html.index('inv-form-page')
        marker = 'inventory/js/inventory_form.js'
        end = html.index('>', html.index(marker, start)) + 1
        return html[start:end]

    def test_add_page_renders(self):
        resp = self.client.get(self.add_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Add Item')
        self.assertContains(resp, 'autofocus')

    def test_edit_page_renders_prefilled(self):
        resp = self.client.get(reverse('inventory:edit_item', args=[self.item.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Edit Item')
        self.assertContains(resp, 'value="5305-01-234-5678"')
        self.assertContains(resp, 'value="Hex bolt"')
        self.assertContains(resp, '5305-01-234-5678')

    def test_valid_post_creates_and_redirects_to_dashboard(self):
        resp = self.client.post(self.add_url, {
            'nsn': '9999-00-000-0001',
            'description': 'New widget',
            'quantity': '3',
            'purchaseprice': '1.50',
        })
        self.assertRedirects(resp, reverse('inventory:dashboard'))
        self.assertTrue(InventoryItem.objects.filter(nsn='9999-00-000-0001').exists())

    def test_add_another_redirects_back_to_add(self):
        resp = self.client.post(self.add_url, {
            'nsn': '9999-00-000-0002',
            'quantity': '1',
            'purchaseprice': '1',
            '_addanother': 'Save & add another',
        })
        self.assertRedirects(resp, self.add_url)
        self.assertTrue(InventoryItem.objects.filter(nsn='9999-00-000-0002').exists())

    def test_negative_quantity_rejected(self):
        before = InventoryItem.objects.count()
        resp = self.client.post(self.add_url, {'nsn': 'neg-qty', 'quantity': '-1'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Quantity cannot be negative.')
        self.assertEqual(InventoryItem.objects.count(), before)

    def test_negative_price_rejected(self):
        before = InventoryItem.objects.count()
        resp = self.client.post(self.add_url, {'nsn': 'neg-price', 'purchaseprice': '-0.01'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Unit price cannot be negative.')
        self.assertEqual(InventoryItem.objects.count(), before)

    def test_blank_quantity_and_price_save_with_null_total(self):
        resp = self.client.post(self.add_url, {
            'nsn': 'blank-cost',
            'description': 'No numbers',
            'quantity': '',
            'purchaseprice': '',
        })
        self.assertRedirects(resp, reverse('inventory:dashboard'))
        item = InventoryItem.objects.get(nsn='blank-cost')
        self.assertIsNone(item.quantity)
        self.assertIsNone(item.purchaseprice)
        self.assertIsNone(item.totalcost)

    def test_add_another_button_only_on_add(self):
        add = self.client.get(self.add_url)
        edit = self.client.get(reverse('inventory:edit_item', args=[self.item.id]))
        self.assertContains(add, 'name="_addanother"')
        self.assertNotContains(edit, 'name="_addanother"')

    def test_form_page_has_no_inline_script(self):
        resp = self.client.get(self.add_url)
        chunk = self._content_block(resp)
        self.assertNotRegex(chunk, r'<script(?![^>]*\bsrc=)')
        self.assertIn('inventory/js/inventory_form.js', chunk)
