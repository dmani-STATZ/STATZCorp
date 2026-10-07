"""Stage 2B — reminder bells on contract management."""
import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from contracts.models import Clin, Company, Contract
from contracts.services import reminders as reminder_service
from users.models import UserCompanyMembership


class ReminderBellContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name='Bell Test Co',
            slug='bell-test-co',
            is_active=True,
        )
        cls.user = get_user_model().objects.create_user(
            username='bell-user',
            password='test-password',
        )
        UserCompanyMembership.objects.create(
            user=cls.user,
            company=cls.company,
            is_default=True,
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()

    def _contract_with_clins(self, count):
        contract = Contract.objects.create(
            company=self.company,
            contract_number=f'BELL-{count}',
        )
        clins = []
        for i in range(count):
            clins.append(Clin.objects.create(
                contract=contract,
                company=self.company,
                item_number=f'{i + 1:04d}',
                item_type='P',
            ))
        return contract, clins

    def test_context_includes_all_clin_status_keys(self):
        contract, clins = self._contract_with_clins(3)
        url = reverse('contracts:contract_management', kwargs={'pk': contract.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        status = response.context['reminder_status']
        for clin in clins:
            self.assertIn(str(clin.pk), status['clins'])

    def test_contract_bell_overdue_when_clin_yesterday(self):
        contract, clins = self._contract_with_clins(2)
        today = date.today()
        reminder_service.create_note_reminder(
            user=self.user,
            target=clins[0],
            label='Overdue clin',
            reminder_date=today - timedelta(days=1),
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )
        url = reverse('contracts:contract_management', kwargs={'pk': contract.pk})
        response = self.client.get(url)
        html = response.content.decode()
        self.assertIn('reminder-bell--overdue', html)
        self.assertIn('reminder-bell--none', html)

    def test_target_list_api_targets_and_title(self):
        contract, _clins = self._contract_with_clins(1)
        url = reverse(
            'contracts:reminder_target_list_api',
            kwargs={'contract_id': contract.pk},
        )
        response = self.client.get(url + '?target_type=contract&target_id=' + str(contract.pk))
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertIn('targets', data)
        self.assertTrue(data['targets'][0]['target_type'] == 'contract')
        self.assertIn('title_label', data)
        self.assertIn(contract.contract_number, data['title_label'])

    def test_status_query_count_independent_of_clin_count(self):
        today = date.today()

        def status_queries(clin_count):
            contract, _ = self._contract_with_clins(clin_count)
            from django.contrib.contenttypes.models import ContentType
            ContentType.objects.get_for_model(Contract)
            ContentType.objects.get_for_model(Clin)
            from django.test.utils import CaptureQueriesContext
            from django.db import connection
            with CaptureQueriesContext(connection) as ctx:
                reminder_service.reminder_status_for_contract(contract, today)
            return len(ctx.captured_queries)

        self.assertEqual(status_queries(2), status_queries(6))
