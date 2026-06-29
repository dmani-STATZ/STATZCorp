"""
Tests for DIBBS contract modification services and the hot-poll mod leak gate.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from contracts.models import Company, Contract
from sales.models import AwardImportBatch, CompanyCAGE, DibbsAward, DibbsAwardMod
from sales.services.awards_file_importer import import_aw_records, is_dibbs_mod_record
from sales.services.awdrecs_parser import parse_awdrecs_html
from sales.services.contract_mods import (
    acknowledge_contract_mod,
    build_award_record_url,
    match_dibbs_award_mod,
    mods_for_contract,
)
from sales.tests.test_awdrecs_parser import WITH_ROWS_HTML

User = get_user_model()


class BuildAwardRecordUrlTests(TestCase):
    def test_po_award_basic_only(self):
        url = build_award_record_url("SPE4A626PT630", "", "")
        self.assertEqual(
            url,
            "https://www.dibbs.bsm.dla.mil/Awards/AwdRec.aspx?contract=SPE4A626PT630&dlv=&cnt=",
        )

    def test_delivery_order(self):
        url = build_award_record_url("SPE4A623D5431", "SPE4A626F197K", "17")
        self.assertEqual(
            url,
            "https://www.dibbs.bsm.dla.mil/Awards/AwdRec.aspx?"
            "contract=SPE4A623D5431&dlv=SPE4A626F197K&cnt=17",
        )

    def test_po_second_example(self):
        url = build_award_record_url("SPE8ED26C0004", "", "")
        self.assertEqual(
            url,
            "https://www.dibbs.bsm.dla.mil/Awards/AwdRec.aspx?contract=SPE8ED26C0004&dlv=&cnt=",
        )

    def test_missing_basic_number_returns_none(self):
        self.assertIsNone(build_award_record_url("", "", ""))


class ModLeakGateTests(TestCase):
    """Hot-poll parser must surface mod posting date so staging classifies MOD rows."""

    def test_parser_extracts_last_mod_posting_date(self):
        rows = parse_awdrecs_html(WITH_ROWS_HTML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Last_Mod_Posting_Date"], "06-02-2026")

    def test_is_dibbs_mod_record_true_when_mod_date_present(self):
        self.assertTrue(
            is_dibbs_mod_record(
                {
                    "Award_Basic_Number": "SPE4A626PT630",
                    "Last_Mod_Posting_Date": "06-02-2026",
                }
            )
        )

    def test_is_dibbs_mod_record_false_for_original_award(self):
        self.assertFalse(
            is_dibbs_mod_record(
                {
                    "Award_Basic_Number": "SPE4A626PT630",
                    "Last_Mod_Posting_Date": "",
                }
            )
        )

    @mock.patch("sales.services.awards_file_importer._call_proc")
    @mock.patch("sales.services.awards_file_importer._stage_rows")
    def test_mod_row_passes_mod_posting_date_to_staging(
        self, mock_stage_rows, mock_call_proc
    ):
        batch = AwardImportBatch.objects.create(
            award_date=date.today(),
            filename="test-hot-poll.txt",
            source=AwardImportBatch.SOURCE_HOT_POLL,
        )
        record = {
            "Award_Basic_Number": "SPE4A626PT630",
            "Delivery_Order_Number": "",
            "Delivery_Order_Counter": "",
            "Last_Mod_Posting_Date": "06-15-2026",
            "Awardee_CAGE_Code": "3WGD1",
            "Total_Contract_Price": "1000.00",
            "Award_Date": "06-01-2026",
            "Posted_Date": "06-15-2026",
            "NSN_Part_Number": "1234567890123",
            "Nomenclature": "WIDGET",
            "Purchase_Request": "",
            "Solicitation": "",
        }
        import_aw_records([record], batch, date.today())

        staged_rows = mock_stage_rows.call_args[0][0]
        self.assertEqual(len(staged_rows), 1)
        self.assertEqual(staged_rows[0].last_mod_posting_date, date(2026, 6, 15))
        self.assertTrue(is_dibbs_mod_record(record))
        mock_call_proc.assert_called_once()


class ContractModMatchingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Mod Test Co", slug="mod-test-co", is_active=True
        )
        self.contract = Contract.objects.create(
            company=self.company,
            contract_number="SPE4A6-26-P-T630",
        )

    def test_match_sets_matched_contract_on_unique_hit(self):
        CompanyCAGE.objects.create(
            cage_code="3WGD1",
            company_name="Test",
            is_active=True,
            sb_representations_code="A",
            affirmative_action_code="Y6",
            previous_contracts_code="Y4",
            alternate_disputes_resolution="A",
        )
        award = DibbsAward.objects.create(
            sol_number="SOL1",
            notice_id="N1",
            award_date=date.today(),
            award_basic_number="SPE4A626PT630",
        )
        mod = DibbsAwardMod.objects.create(
            award=award,
            award_basic_number="SPE4A626PT630",
            awardee_cage="3WGD1",
            mod_date=date.today(),
        )
        self.assertTrue(match_dibbs_award_mod(mod))
        mod.refresh_from_db()
        self.assertEqual(mod.matched_contract_id, self.contract.id)

    def test_match_never_overwrites_existing_link(self):
        other = Contract.objects.create(
            company=self.company,
            contract_number="SPE4A6-26-P-OTHER",
        )
        award = DibbsAward.objects.create(
            sol_number="SOL2",
            notice_id="N2",
            award_date=date.today(),
            award_basic_number="SPE4A626PT630",
        )
        mod = DibbsAwardMod.objects.create(
            award=award,
            award_basic_number="SPE4A626PT630",
            mod_date=date.today(),
            matched_contract=other,
        )
        self.assertFalse(match_dibbs_award_mod(mod))
        mod.refresh_from_db()
        self.assertEqual(mod.matched_contract_id, other.id)

    def test_partner_cage_included_in_matching_gate(self):
        from sales.constants import PARTNER_CAGES
        from sales.services.contract_mods import active_company_cage_codes

        self.assertIn("64W95", PARTNER_CAGES)
        self.assertIn("64W95", active_company_cage_codes())

    def test_match_new_mods_includes_partner_cage(self):
        from sales.services.contract_mods import match_new_mods_after_import

        award = DibbsAward.objects.create(
            sol_number="SOL-ETP",
            notice_id="N-ETP",
            award_date=date.today(),
            award_basic_number="SPE4A626PT630",
        )
        mod = DibbsAwardMod.objects.create(
            award=award,
            award_basic_number="SPE4A626PT630",
            awardee_cage="64W95",
            mod_date=date.today(),
        )
        before_id = mod.id - 1
        matched = match_new_mods_after_import(before_max_mod_id=before_id)
        mod.refresh_from_db()
        self.assertEqual(matched, 1)
        self.assertEqual(mod.matched_contract_id, self.contract.id)


class ContractModServiceTests(TestCase):
    def test_mods_for_contract_ordering_and_labels(self):
        company = Company.objects.create(
            name="Mods List Co", slug="mods-list-co", is_active=True
        )
        contract = Contract.objects.create(
            company=company,
            contract_number="SPE8ED-26-C-0004",
        )
        award = DibbsAward.objects.create(
            sol_number="SOL3",
            notice_id="N3",
            award_date=date.today(),
            award_basic_number="SPE8ED26C0004",
        )
        DibbsAwardMod.objects.create(
            award=award,
            award_basic_number="SPE8ED26C0004",
            mod_date=date(2026, 3, 1),
            mod_contract_price=Decimal("100.00"),
            matched_contract=contract,
        )
        DibbsAwardMod.objects.create(
            award=award,
            award_basic_number="SPE8ED26C0004",
            mod_date=date(2026, 4, 1),
            mod_contract_price=Decimal("200.00"),
            matched_contract=contract,
        )
        items = mods_for_contract(contract)
        self.assertEqual([i.label for i in items], ["Mod #1", "Mod #2"])
        self.assertIn("SPE8ED26C0004", items[0].award_record_url or "")

    def test_acknowledge_is_idempotent(self):
        user = User.objects.create_user(username="moduser", password="x")
        award = DibbsAward.objects.create(
            sol_number="SOL4",
            notice_id="N4",
            award_date=date.today(),
            award_basic_number="SPE4A626PT630",
        )
        mod = DibbsAwardMod.objects.create(
            award=award,
            award_basic_number="SPE4A626PT630",
            mod_date=date.today(),
        )
        acknowledge_contract_mod(mod, user)
        first_at = mod.acknowledged_at
        acknowledge_contract_mod(mod, user)
        mod.refresh_from_db()
        self.assertEqual(mod.acknowledged_at, first_at)
        self.assertEqual(mod.acknowledged_by_id, user.id)
