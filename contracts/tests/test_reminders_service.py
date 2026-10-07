"""Tests for contracts.services.reminders and Stage 1 reminder APIs."""
import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from contracts.models import Clin, ClinAcknowledgment, Company, Contract, Reminder
from contracts.services import reminders as reminder_service
from users.models import UserCompanyMembership


class RemindersServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            name='Reminders Test Co',
            slug='reminders-test-co',
            is_active=True,
        )
        cls.user = get_user_model().objects.create_user(
            username='reminders-user',
            password='test-password',
        )
        UserCompanyMembership.objects.create(
            user=cls.user,
            company=cls.company,
            is_default=True,
        )
        cls.other_company = Company.objects.create(
            name='Other Co',
            slug='other-co',
            is_active=True,
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()
        self.today = date(2026, 6, 15)

    def _contract(self, **kwargs):
        defaults = {
            'company': self.company,
            'contract_number': 'SPE-REM-TEST',
        }
        defaults.update(kwargs)
        return Contract.objects.create(**defaults)

    def _clin(self, contract, **kwargs):
        defaults = {
            'contract': contract,
            'company': self.company,
            'item_number': '0001',
            'item_type': 'P',
        }
        defaults.update(kwargs)
        return Clin.objects.create(**defaults)

    def test_checkin_set_grouping(self):
        contract = self._contract()
        due = date(2026, 12, 1)
        self._clin(contract, item_number='0001', item_type='P', supplier_due_date=due)
        self._clin(contract, item_number='0002', item_type='P', supplier_due_date=due)
        self._clin(contract, item_number='0003', item_type='G', supplier_due_date=due)
        self._clin(contract, item_number='0004', item_type='P', supplier_due_date=None)

        clins = reminder_service._clins_for_contract(contract)
        checkin = reminder_service._checkin_clins(clins)
        item_numbers = sorted(c.item_number for c in checkin)
        self.assertEqual(item_numbers, ['0001', '0003'])

        rows = reminder_service.compute_reminder_presets(contract, self.today)
        first_checkin_rows = [r for r in rows if r['preset_key'] == reminder_service.FIRST_CHECKIN]
        self.assertEqual(len(first_checkin_rows), 2)

    def test_ack_followup_fallback_today_plus_10(self):
        contract = self._contract()
        self._clin(contract, item_type='P')
        rows = reminder_service.compute_reminder_presets(contract, self.today)
        ack = next(r for r in rows if r['preset_key'] == reminder_service.ACK_FOLLOWUP)
        self.assertEqual(ack['reminder_date'], (self.today + timedelta(days=10)).isoformat())

    def test_ack_followup_uses_po_to_supplier_date(self):
        contract = self._contract()
        clin = self._clin(contract, item_type='P')
        po_date = date(2026, 5, 1)
        ClinAcknowledgment.objects.create(clin=clin, po_to_supplier_date=po_date)
        rows = reminder_service.compute_reminder_presets(contract, self.today)
        ack = next(r for r in rows if r['preset_key'] == reminder_service.ACK_FOLLOWUP)
        self.assertEqual(ack['reminder_date'], (po_date + timedelta(days=10)).isoformat())

    def test_mid_contract_skipped_without_dates(self):
        contract = self._contract(award_date=None, due_date=None)
        self._clin(contract)
        rows = reminder_service.compute_reminder_presets(contract, self.today)
        self.assertFalse(any(r['preset_key'] == reminder_service.MID_CONTRACT for r in rows))

    def test_pre_due_contract_fallback_when_checkin_empty(self):
        contract = self._contract(due_date=date(2026, 9, 1))
        self._clin(contract, item_type='P', supplier_due_date=None)
        rows = reminder_service.compute_reminder_presets(contract, self.today)
        pre = [r for r in rows if r['preset_key'] == reminder_service.PRE_DUE]
        self.assertEqual(len(pre), 1)
        self.assertEqual(pre[0]['target_type'], 'contract')
        self.assertEqual(pre[0]['reminder_date'], date(2026, 8, 2).isoformat())

    def test_default_checked_and_is_past(self):
        contract = self._contract(
            award_date=date(2020, 1, 1),
            due_date=date(2020, 6, 1),
        )
        self._clin(contract, item_type='P', supplier_due_date=date(2020, 3, 1))
        rows = reminder_service.compute_reminder_presets(contract, self.today)
        mid = next(r for r in rows if r['preset_key'] == reminder_service.MID_CONTRACT)
        self.assertTrue(mid['is_past'])
        self.assertFalse(mid['default_checked'])

    def test_already_set_and_bulk_skip(self):
        contract = self._contract(due_date=date(2026, 12, 1))
        clin = self._clin(contract, supplier_due_date=date(2026, 12, 1))
        reminder_service.create_note_reminder(
            user=self.user,
            target=clin,
            label='FIRST SUPPLIER CHECK IN',
            reminder_date=date(2026, 10, 1),
            preset_key=reminder_service.FIRST_CHECKIN,
            company=self.company,
        )
        rows = reminder_service.compute_reminder_presets(contract, self.today)
        fc = next(
            r for r in rows
            if r['preset_key'] == reminder_service.FIRST_CHECKIN and r['target_id'] == clin.pk
        )
        self.assertTrue(fc['already_set'])

        payload_rows = [{
            'preset_key': reminder_service.FIRST_CHECKIN,
            'label': 'FIRST SUPPLIER CHECK IN',
            'target_type': 'clin',
            'target_id': clin.pk,
            'reminder_date': '2026-10-01',
        }]
        result = reminder_service.bulk_create_note_reminders(
            user=self.user,
            contract=contract,
            rows=payload_rows,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['created'], [])
        self.assertEqual(result['skipped'], [0])

    def test_status_due_today_pending_yesterday_overdue(self):
        contract = self._contract()
        clin_a = self._clin(contract, item_number='0001')
        clin_b = self._clin(contract, item_number='0002')
        reminder_service.create_note_reminder(
            user=self.user,
            target=clin_a,
            label='Due today',
            reminder_date=self.today,
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )
        reminder_service.create_note_reminder(
            user=self.user,
            target=clin_b,
            label='Overdue',
            reminder_date=self.today - timedelta(days=1),
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )
        status = reminder_service.reminder_status_for_contract(contract, self.today)
        self.assertEqual(status['contract']['state'], 'overdue')
        self.assertEqual(status['clins'][str(clin_a.pk)]['state'], 'pending')
        self.assertEqual(status['clins'][str(clin_b.pk)]['state'], 'overdue')

    def test_status_ignores_completed(self):
        contract = self._contract()
        clin = self._clin(contract)
        reminder = reminder_service.create_note_reminder(
            user=self.user,
            target=clin,
            label='Done',
            reminder_date=self.today - timedelta(days=5),
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )
        reminder.reminder_completed = True
        reminder.save(update_fields=['reminder_completed'])
        status = reminder_service.reminder_status_for_contract(contract, self.today)
        self.assertEqual(status['contract']['state'], 'none')
        self.assertEqual(status['clins'][str(clin.pk)]['state'], 'none')

    def test_status_query_budget(self):
        ContentType.objects.get_for_model(Contract)
        ContentType.objects.get_for_model(Clin)
        contract = self._contract()
        self._clin(contract, item_number='0001')
        self._clin(contract, item_number='0002')
        with self.assertNumQueries(2):
            reminder_service.reminder_status_for_contract(contract, self.today)

    def test_extend_rules(self):
        contract = self._contract()
        clin = self._clin(contract)
        reminder = reminder_service.create_note_reminder(
            user=self.user,
            target=clin,
            label='Extend me',
            reminder_date=date(2026, 6, 1),
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )
        reminder_service.extend_reminder(reminder, days=3, today=self.today)
        reminder.refresh_from_db()
        self.assertEqual(reminder.original_reminder_date, date(2026, 6, 1))
        self.assertEqual(reminder.reminder_date, self.today + timedelta(days=3))
        self.assertEqual(reminder.extension_count, 1)

        reminder_service.extend_reminder(reminder, days=7, today=self.today)
        reminder.refresh_from_db()
        self.assertEqual(reminder.original_reminder_date, date(2026, 6, 1))
        self.assertEqual(reminder.extension_count, 2)

        with self.assertRaises(ValueError):
            reminder_service.extend_reminder(
                reminder,
                new_date=self.today - timedelta(days=1),
                today=self.today,
            )

        reminder.reminder_completed = True
        reminder.save(update_fields=['reminder_completed'])
        with self.assertRaises(ValueError):
            reminder_service.extend_reminder(reminder, days=3, today=self.today)

    def test_bulk_create_atomic_on_invalid_row(self):
        contract = self._contract()
        clin = self._clin(contract)
        before = Reminder.objects.count()
        result = reminder_service.bulk_create_note_reminders(
            user=self.user,
            contract=contract,
            rows=[
                {
                    'preset_key': reminder_service.CUSTOM,
                    'label': 'Valid',
                    'target_type': 'clin',
                    'target_id': clin.pk,
                    'reminder_date': '2026-08-01',
                },
                {
                    'preset_key': 'not-a-preset',
                    'label': 'Bad',
                    'target_type': 'clin',
                    'target_id': clin.pk,
                    'reminder_date': '2026-08-01',
                },
            ],
        )
        self.assertFalse(result['ok'])
        self.assertEqual(Reminder.objects.count(), before)

    def test_null_completed_counts_as_pending_in_status_and_list(self):
        contract = self._contract()
        clin = self._clin(contract)
        reminder = reminder_service.create_note_reminder(
            user=self.user,
            target=clin,
            label='Null completion pending',
            reminder_date=self.today,
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )
        Reminder.objects.filter(pk=reminder.pk).update(reminder_completed=None)

        status = reminder_service.reminder_status_for_contract(contract, self.today)
        self.assertEqual(status['contract']['state'], 'pending')
        self.assertEqual(status['clins'][str(clin.pk)]['pending'], 1)

        listed = reminder_service.pending_reminders_for_target(
            contract,
            target_type='clin',
            target_id=clin.pk,
            today=self.today,
        )
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].pk, reminder.pk)

    def test_reminder_title_truncated_reminder_text_full(self):
        contract = self._contract()
        clin = self._clin(contract)
        label = 'L' * 60
        reminder = reminder_service.create_note_reminder(
            user=self.user,
            target=clin,
            label=label,
            reminder_date=self.today,
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )
        self.assertEqual(len(reminder.reminder_title), 50)
        self.assertEqual(reminder.reminder_title, label[:50])
        self.assertEqual(reminder.reminder_text, label)

    def test_bulk_create_rejects_label_over_200_chars(self):
        contract = self._contract()
        clin = self._clin(contract)
        before = Reminder.objects.count()
        result = reminder_service.bulk_create_note_reminders(
            user=self.user,
            contract=contract,
            rows=[{
                'preset_key': reminder_service.CUSTOM,
                'label': 'X' * 201,
                'target_type': 'clin',
                'target_id': clin.pk,
                'reminder_date': '2026-08-01',
            }],
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['errors'][0]['message'], 'Label must be 200 characters or fewer.')
        self.assertEqual(Reminder.objects.count(), before)

    def test_ack_followup_already_set_when_pending_on_clin(self):
        contract = self._contract()
        clin = self._clin(contract, item_type='P')
        reminder_service.create_note_reminder(
            user=self.user,
            target=clin,
            label='PO ACKNOWLEDGMENT LETTER Followup',
            reminder_date=self.today + timedelta(days=10),
            preset_key=reminder_service.ACK_FOLLOWUP,
            company=self.company,
        )
        rows = reminder_service.compute_reminder_presets(contract, self.today)
        ack = next(r for r in rows if r['preset_key'] == reminder_service.ACK_FOLLOWUP)
        self.assertTrue(ack['already_set'])
        self.assertEqual(ack['target_type'], 'contract')

        result = reminder_service.bulk_create_note_reminders(
            user=self.user,
            contract=contract,
            rows=[{
                'preset_key': reminder_service.ACK_FOLLOWUP,
                'label': ack['label'],
                'target_type': 'contract',
                'target_id': contract.pk,
                'reminder_date': ack['reminder_date'],
            }],
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['created'], [])
        self.assertEqual(result['skipped'], [0])

    def test_presets_api_other_company_404(self):
        contract = Contract.objects.create(
            company=self.other_company,
            contract_number='OTHER-CONTRACT',
        )
        url = reverse('contracts:reminder_presets_api', kwargs={'contract_id': contract.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class ReminderExtendApiTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Extend API Co',
            slug='extend-api-co',
            is_active=True,
        )
        self.user = get_user_model().objects.create_user(
            username='extend-user',
            password='test-password',
        )
        UserCompanyMembership.objects.create(
            user=self.user,
            company=self.company,
            is_default=True,
        )
        self.non_owner = get_user_model().objects.create_user(
            username='non-owner-user',
            password='test-password',
        )
        UserCompanyMembership.objects.create(
            user=self.non_owner,
            company=self.company,
            is_default=True,
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number='EXT-TEST',
        )
        self.clin = Clin.objects.create(
            contract=self.contract,
            company=self.company,
            item_number='0001',
            item_type='P',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()

        self.reminder = reminder_service.create_note_reminder(
            user=self.user,
            target=self.clin,
            label='Extend via API',
            reminder_date=date(2026, 6, 1),
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )

    def test_extend_forbidden_for_non_owner(self):
        self.client.force_login(self.non_owner)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()
        url = reverse('contracts:reminder_extend_api', kwargs={'pk': self.reminder.pk})
        response = self.client.post(
            url,
            data=json.dumps({'days': 3}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)
