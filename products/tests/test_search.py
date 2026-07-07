from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from products.models import Nsn
from products.nsn_utils import normalize_nsn

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
