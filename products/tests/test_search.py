from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from products.models import Nsn
from products.nsn_utils import normalize_nsn
from sales.models.sam_cache import SAMEntityCache
from suppliers.models import Supplier

User = get_user_model()


class PortalSearchClassifierTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='portal', password='test')
        self.client.login(username='portal', password='test')
        self.nsn = Nsn.objects.create(nsn_code='5935-01-129-9512', description='Test widget')

    def test_full_nsn_redirects_to_dossier(self):
        resp = self.client.get(reverse('products:portal_search'), {'q': '5935-01-129-9512'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('products:nsn_detail', kwargs={'pk': self.nsn.pk}))

    def test_bare_nsn_redirects(self):
        resp = self.client.get(reverse('products:portal_search'), {'q': '5935011299512'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('products:nsn_detail', kwargs={'pk': self.nsn.pk}))

    def test_niin_search_finds_nsn(self):
        niin = normalize_nsn('5935011299512')[4:]
        resp = self.client.get(reverse('products:portal_search'), {'q': niin})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.nsn.nsn_code)

    def test_part_number_search(self):
        self.nsn.part_number = 'WIDGET-42'
        self.nsn.save()
        resp = self.client.get(reverse('products:portal_search'), {'q': 'WIDGET-42'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'WIDGET-42')

    def test_full_nsn_matches_when_nsn_normalized_empty(self):
        """SQL MERGE rows can have nsn_code set but nsn_normalized blank."""
        self.nsn.nsn_code = '4810-01-124-3692'
        self.nsn.save()
        Nsn.objects.filter(pk=self.nsn.pk).update(nsn_normalized='')
        resp = self.client.get(reverse('products:portal_search'), {'q': '4810-01-124-3692'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('products:nsn_detail', kwargs={'pk': self.nsn.pk}))

    def test_niin_matches_when_nsn_normalized_empty(self):
        self.nsn.nsn_code = '4810-01-124-3692'
        self.nsn.save()
        Nsn.objects.filter(pk=self.nsn.pk).update(nsn_normalized='')
        niin = normalize_nsn('4810011243692')[4:]
        resp = self.client.get(reverse('products:portal_search'), {'q': niin})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '4810-01-124-3692')

    def test_cage_single_supplier_redirects_to_supplier_nsns(self):
        supplier = Supplier.objects.create(name='Acme Supply', cage_code='1BRD5')
        resp = self.client.get(reverse('products:portal_search'), {'q': '1BRD5'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            reverse('products:supplier_nsns', kwargs={'pk': supplier.pk}),
        )

    def test_cage_hyphenated_input_still_matches(self):
        supplier = Supplier.objects.create(name='Numeric Cage Co', cage_code='81205')
        resp = self.client.get(reverse('products:portal_search'), {'q': '81-205'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            reverse('products:supplier_nsns', kwargs={'pk': supplier.pk}),
        )

    def test_cage_padded_supplier_code_still_matches(self):
        supplier = Supplier.objects.create(name='Padded Cage Co', cage_code='ZPAD1   ')
        resp = self.client.get(reverse('products:portal_search'), {'q': 'ZPAD1'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            reverse('products:supplier_nsns', kwargs={'pk': supplier.pk}),
        )

    def test_cage_sam_only_renders_sam_notice(self):
        SAMEntityCache.objects.create(
            cage_code='SAM01',
            entity_name='SAM Only Corp',
            last_fetched=timezone.now(),
        )
        resp = self.client.get(reverse('products:portal_search'), {'q': 'SAM01'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'SAM cache')
        self.assertContains(resp, 'SAM Only Corp')

    def test_cage_no_match_renders_empty_state(self):
        resp = self.client.get(reverse('products:portal_search'), {'q': 'ZZZZZ'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No matches')
