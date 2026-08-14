from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from contracts.forms import NsnForm
from products.models import Nsn

User = get_user_model()

_CODE_A = '5935-01-129-9512'
_CODE_A_BARE = '5935011299512'
_CODE_B = '4730-00-125-6889'


def _form(data, instance=None):
    return NsnForm(data, instance=instance)


class NsnFormDedupTests(TestCase):
    def test_create_with_new_code_succeeds(self):
        form = _form({'nsn_code': _CODE_A, 'description': 'Connector'})
        self.assertTrue(form.is_valid(), form.errors)
        nsn = form.save()
        self.assertEqual(nsn.nsn_normalized, '5935011299512')
        self.assertEqual(Nsn.objects.filter(nsn_normalized='5935011299512').count(), 1)

    def test_create_with_normalized_duplicate_fails(self):
        Nsn.objects.create(nsn_code=_CODE_A, description='Existing')
        form = _form({'nsn_code': _CODE_A_BARE, 'description': 'Duplicate attempt'})
        self.assertFalse(form.is_valid())
        self.assertIn('nsn_code', form.errors)
        self.assertIn('already exists', form.errors['nsn_code'][0])
        self.assertIn(str(Nsn.objects.get(nsn_code=_CODE_A).pk), form.errors['nsn_code'][0])

    def test_edit_description_on_legacy_duplicate_succeeds(self):
        """Editing a non-code field must not block saves on already-duplicate rows."""
        first = Nsn.objects.create(nsn_code=_CODE_A, description='First')
        sibling = Nsn.objects.create(nsn_code=_CODE_A_BARE, description='Second')
        self.assertEqual(first.nsn_normalized, sibling.nsn_normalized)
        self.assertNotEqual(first.pk, sibling.pk)

        form = _form(
            {'nsn_code': sibling.nsn_code, 'description': 'Fixed typo'},
            instance=sibling,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.pk, sibling.pk)
        self.assertEqual(saved.description, 'Fixed typo')
        self.assertEqual(saved.nsn_code, _CODE_A_BARE)

    def test_edit_nsn_code_to_collide_with_other_nsn_fails(self):
        Nsn.objects.create(nsn_code=_CODE_A, description='Keep')
        other = Nsn.objects.create(nsn_code=_CODE_B, description='Change me')
        form = _form(
            {'nsn_code': _CODE_A, 'description': other.description},
            instance=other,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('nsn_code', form.errors)
        self.assertIn('already exists', form.errors['nsn_code'][0])


class NsnCreateViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='nsn_create', password='test')
        self.client.login(username='nsn_create', password='test')

    def test_get_prefills_nsn_code_from_query(self):
        resp = self.client.get(reverse('products:nsn_create'), {'nsn_code': _CODE_A})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Create NSN')
        self.assertContains(resp, _CODE_A)

    def test_post_creates_and_redirects_to_dossier(self):
        resp = self.client.post(reverse('products:nsn_create'), {
            'nsn_code': _CODE_A,
            'description': 'New catalog row',
        })
        nsn = Nsn.objects.get(nsn_code=_CODE_A)
        self.assertEqual(nsn.created_by, self.user)
        self.assertEqual(nsn.modified_by, self.user)
        self.assertRedirects(
            resp,
            reverse('products:nsn_detail', kwargs={'pk': nsn.pk}),
            fetch_redirect_response=False,
        )

    def test_post_rejects_normalized_duplicate(self):
        Nsn.objects.create(nsn_code=_CODE_A)
        resp = self.client.post(reverse('products:nsn_create'), {
            'nsn_code': _CODE_A_BARE,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')
        self.assertEqual(Nsn.objects.filter(nsn_normalized='5935011299512').count(), 1)
