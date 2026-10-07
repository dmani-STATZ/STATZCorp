"""Tests for contract-level acknowledgment toggle (Stage 2A — no silent reminders)."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from contracts.models import Clin, ClinAcknowledgment, Company, Contract, Note, Reminder
from contracts.services import reminders as reminder_service
from users.models import UserCompanyMembership


class ToggleContractAcknowledgmentTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Ack Toggle Co',
            slug='ack-toggle-co',
            is_active=True,
        )
        self.user = get_user_model().objects.create_user(
            username='ack-toggle-user',
            password='test-password',
        )
        UserCompanyMembership.objects.create(
            user=self.user,
            company=self.company,
            is_default=True,
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number='ACK-TOGGLE-TEST',
        )
        self.clin = Clin.objects.create(
            contract=self.contract,
            company=self.company,
            item_number='0001',
            item_type='P',
            supplier_due_date='2026-12-01',
        )
        ClinAcknowledgment.objects.create(clin=self.clin, po_to_supplier_bool=False)
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()
        self.url = reverse(
            'contracts:toggle_contract_acknowledgment',
            kwargs={'contract_id': self.contract.pk},
        )

    def test_po_sent_prompts_without_creating_notes_or_reminders(self):
        before_notes = Note.objects.count()
        before_reminders = Reminder.objects.count()
        response = self.client.post(
            self.url,
            data=json.dumps({'field': 'po_to_supplier_bool'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['status'])
        self.assertTrue(data['prompt_set_reminders'])
        self.assertEqual(Note.objects.count(), before_notes)
        self.assertEqual(Reminder.objects.count(), before_reminders)

    def test_po_already_sent_does_not_prompt_again(self):
        ack = self.clin.clinacknowledgment_set.first()
        ack.po_to_supplier_bool = True
        ack.save(update_fields=['po_to_supplier_bool'])
        response = self.client.post(
            self.url,
            data=json.dumps({'field': 'po_to_supplier_bool'}),
            content_type='application/json',
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.assertFalse(data['prompt_set_reminders'])

    def test_non_po_ack_field_does_not_prompt(self):
        response = self.client.post(
            self.url,
            data=json.dumps({'field': 'clin_reply_bool'}),
            content_type='application/json',
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['status'])
        self.assertFalse(data['prompt_set_reminders'])

    def test_create_note_reminder_sets_completed_false(self):
        reminder = reminder_service.create_note_reminder(
            user=self.user,
            target=self.clin,
            label='Explicit pending',
            reminder_date='2026-08-01',
            preset_key=reminder_service.CUSTOM,
            company=self.company,
        )
        self.assertIs(reminder.reminder_completed, False)
