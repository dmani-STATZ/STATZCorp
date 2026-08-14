import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from products.models import Nsn

User = get_user_model()

_CODE = '5935-01-129-9512'
_CODE_BARE = '5935011299512'
_OVERFLOW = 'M1222ST4NABCDEFNCNN'


class CreateNsnApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='api_nsn', password='test')
        self.client.login(username='api_nsn', password='test')
        self.url = reverse('contracts:api_nsn_create')

    def _post(self, payload):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_create_with_nsn_code_key_succeeds(self):
        resp = self._post({'nsn_code': _CODE, 'description': 'Connector'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        nsn = Nsn.objects.get(pk=data['id'])
        self.assertEqual(nsn.nsn_code, _CODE)
        self.assertEqual(data['label'], f'{_CODE} - Connector')
        self.assertEqual(nsn.created_by, self.user)

    def test_legacy_nsn_key_still_works(self):
        """processing/nsn_modal.js posts {nsn, description} — do not break that."""
        resp = self._post({'nsn': _CODE, 'description': 'From processing'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(Nsn.objects.get(pk=data['id']).nsn_code, _CODE)

    def test_missing_code_returns_400(self):
        resp = self._post({'description': 'No code'})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['success'])

    def test_normalized_duplicate_returns_existing(self):
        existing = Nsn.objects.create(nsn_code=_CODE, description='Keep')
        resp = self._post({'nsn_code': _CODE_BARE, 'description': 'Dup'})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['existing_id'], existing.pk)
        self.assertIn(str(existing.pk), data['error'])
        self.assertEqual(Nsn.objects.filter(nsn_normalized='5935011299512').count(), 1)

    def test_overflow_code_falls_back_to_exact_match(self):
        Nsn.objects.create(nsn_code=_OVERFLOW, description='Overflow')
        resp = self._post({'nsn_code': _OVERFLOW})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['success'])
        self.assertEqual(Nsn.objects.filter(nsn_code=_OVERFLOW).count(), 1)
