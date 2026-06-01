import os
import django
import sys
from decimal import Decimal

# Set up Django environment
sys.path.append(r'C:\Users\Dion\Documents\STATZWeb\STATZCorp')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings')
django.setup()

from contracts.models import ContractLevelCharge, Contract, Company, Clin, ContractStatus
from processing.models import ProcessContractCharge, ProcessContract, ProcessClin
from django.db import connection

def verify_stage_1():
    print("--- Verification Stage 1 Started ---")
    
    # 1. Check imports
    try:
        from contracts.models import ContractLevelCharge
        from processing.models import ProcessContractCharge
        print("PASS: Imported ContractLevelCharge and ProcessContractCharge successfully.")
    except Exception as e:
        print(f"FAIL: Imports failed: {e}")
        return False

    # 2. Confirm tables exist in DB
    tables = connection.introspection.table_names()
    if 'contracts_contractlevelcharge' in tables:
        print("PASS: Table 'contracts_contractlevelcharge' exists in the database.")
    else:
        print("FAIL: Table 'contracts_contractlevelcharge' does not exist in the database.")
        return False
        
    if 'processing_processcontractcharge' in tables:
        print("PASS: Table 'processing_processcontractcharge' exists in the database.")
    else:
        print("FAIL: Table 'processing_processcontractcharge' does not exist in the database.")
        return False

    # 3. Confirm calculate_plan_gross() logic
    # Setup test objects in an atomic block that we roll back
    from django.db import transaction
    try:
        with transaction.atomic():
            company = Company.objects.first()
            if not company:
                company = Company.objects.create(name="Test Company", slug="test-company")
                
            pc = ProcessContract.objects.create(
                company=company,
                contract_number="TEST-PC-123",
                packhouse_quote_amount=Decimal("100.00"),
                contract_value=Decimal("1000.00")
            )
            ProcessClin.objects.create(
                process_contract=pc,
                item_number="0001",
                item_value=Decimal("1000.00"),
                quote_value=Decimal("600.00"),
                order_qty=1.0,
                unit_price=Decimal("1000.00")
            )
            
            # Initial plan gross without charges:
            # item_total (1000.00) - quote_total (600.00) - packhouse (100.00) = 300.00
            pc.update_calculated_values()
            print(f"Plan gross without charges: {pc.plan_gross}")
            if pc.plan_gross != Decimal("300.00"):
                print(f"FAIL: Plan gross without charges should be 300.00, got {pc.plan_gross}")
                raise AssertionError()
                
            # Add a charge
            ProcessContractCharge.objects.create(
                process_contract=pc,
                label="GSI Fee",
                estimated_amount=Decimal("50.00")
            )
            
            # Recalculate: should be 300.00 - 50.00 = 250.00
            pc.update_calculated_values()
            print(f"Plan gross with GSI Fee: {pc.plan_gross}")
            if pc.plan_gross != Decimal("250.00"):
                print(f"FAIL: Plan gross with GSI Fee should be 250.00, got {pc.plan_gross}")
                raise AssertionError()
                
            print("PASS: ProcessContract.calculate_plan_gross() subtracts charges correctly.")
            
            # 4. Confirm Contract.adjusted_gross logic
            status, _ = ContractStatus.objects.get_or_create(description="Open")
            c = Contract.objects.create(
                company=company,
                contract_number="TEST-C-123",
                status=status
            )
            Clin.objects.create(
                contract=c,
                item_number="0001",
                item_value=Decimal("1000.00"),
                quote_value=Decimal("600.00"),
                order_qty=1.0,
                unit_price=Decimal("1000.00")
            )
            # adjusted_gross without charges: CLIN item_value (1000.00) - quote_value (600.00) = 400.00
            print(f"Contract adjusted gross without charges: {c.adjusted_gross}")
            if c.adjusted_gross != Decimal("400.00"):
                print(f"FAIL: adjusted_gross without charges should be 400.00, got {c.adjusted_gross}")
                raise AssertionError()
                
            # Add ContractLevelCharge
            ContractLevelCharge.objects.create(
                contract=c,
                label="Freight",
                estimated_amount=Decimal("80.00")
            )
            # adjusted_gross with estimated charge: 400.00 - 80.00 = 320.00
            print(f"Contract adjusted gross with estimated charge: {c.adjusted_gross}")
            if c.adjusted_gross != Decimal("320.00"):
                print(f"FAIL: adjusted_gross with estimated charge should be 320.00, got {c.adjusted_gross}")
                raise AssertionError()
                
            # Update billed/paid amount to 90.00
            charge = c.level_charges.first()
            charge.billed_paid_amount = Decimal("90.00")
            charge.save()
            
            # adjusted_gross with billed charge: 400.00 - 90.00 = 310.00
            print(f"Contract adjusted gross with billed charge: {c.adjusted_gross}")
            if c.adjusted_gross != Decimal("310.00"):
                print(f"FAIL: adjusted_gross with billed charge should be 310.00, got {c.adjusted_gross}")
                raise AssertionError()
                
            print("PASS: Contract.adjusted_gross subtracts charges_deduction correctly with COALESCE logic.")
            
            # 5. Check FinanceAuditView get_context_data and finance_audit_summary_api
            from django.test import RequestFactory
            from contracts.views.finance_views import FinanceAuditView, finance_audit_summary_api
            from django.contrib.auth.models import User
            
            rf = RequestFactory()
            user = User.objects.create_user(username='test_finance_user', password='password')
            
            req = rf.get(f'/contracts/finance-audit/{c.id}/')
            req.user = user
            req.active_company = company
            
            view = FinanceAuditView()
            view.request = req
            view.kwargs = {'pk': c.id}
            view.object = c
            
            context = view.get_context_data()
            print(f"Context charges_deduction: {context.get('charges_deduction')}")
            if context.get('charges_deduction') != Decimal("90.00"):
                print(f"FAIL: Context charges_deduction should be 90.00, got {context.get('charges_deduction')}")
                raise AssertionError()
            if 'level_charges' not in context:
                print("FAIL: level_charges not in context")
                raise AssertionError()
            if context.get('adj_gross_contract') != Decimal("310.00"):
                print(f"FAIL: Context adj_gross_contract should be 310.00, got {context.get('adj_gross_contract')}")
                raise AssertionError()
            print("PASS: FinanceAuditView carries correct charges_deduction and level_charges.")

            # Test finance_audit_summary_api
            req_api = rf.get(f'/contracts/api/finance-audit/{c.id}/summary/')
            req_api.user = user
            req_api.active_company = company
            
            response = finance_audit_summary_api(req_api, contract_id=c.id)
            import json
            res_data = json.loads(response.content)
            print(f"API Response adj_gross_contract: {res_data.get('adj_gross_contract')}")
            if Decimal(res_data.get('adj_gross_contract')) != Decimal('310.00'):
                print(f"FAIL: API Response adj_gross_contract should be '310.00', got {res_data.get('adj_gross_contract')}")
                raise AssertionError()
            print("PASS: finance_audit_summary_api returns correct adj_gross_contract.")
            
            transaction.set_rollback(True)
    except Exception as e:
        print(f"FAIL: DB logic tests encountered exception: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    print("--- Verification Stage 1 Completed Successfully ---")
    return True

if __name__ == '__main__':
    verify_stage_1()
