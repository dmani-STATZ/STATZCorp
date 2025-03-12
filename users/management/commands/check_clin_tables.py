from django.core.management.base import BaseCommand
from django.db import connection
from contracts.models import Clin, SpecialPaymentTerms
import json

class Command(BaseCommand):
    help = 'Checks Clin table structure for migration'

    def handle(self, *args, **options):
        # Get Clin model fields
        clin_fields = [field.name for field in Clin._meta.get_fields() 
                      if not field.is_relation or field.one_to_one or field.many_to_one]
        
        # Get SpecialPaymentTerms codes
        special_payment_terms = list(SpecialPaymentTerms.objects.values('id', 'code', 'terms'))
        
        # Get Django table names
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name LIKE 'contracts_%'
            """)
            django_tables = [row[0] for row in cursor.fetchall()]
        
        # Output information
        self.stdout.write(self.style.SUCCESS('Django Table Names:'))
        for table in django_tables:
            self.stdout.write(f'  - {table}')
        
        self.stdout.write('\n' + self.style.SUCCESS('Clin Model Fields:'))
        for field in clin_fields:
            self.stdout.write(f'  - {field}')
        
        self.stdout.write('\n' + self.style.SUCCESS('Special Payment Terms:'))
        for term in special_payment_terms:
            self.stdout.write(f'  - ID: {term["id"]}, Code: {term["code"]}, Terms: {term["terms"]}')
        
        # Generate SQL field mappings
        self.stdout.write('\n' + self.style.SUCCESS('Suggested SQL Field Mappings:'))
        
        # Clin mappings
        self.stdout.write(self.style.SUCCESS('\nClin Mappings:'))
        clin_mappings = {
            'id': 'ID',
            'contract_id': 'Contract_ID',
            'sub_contract': '[Sub-Contract]',
            'po_num_ext': 'PONumExt',
            'tab_num': 'TabNum',
            'clin_po_num': 'SubPONum',
            'po_number': 'PONumber',
            'clin_type_id': 'Type_ID',
            'supplier_id': 'Vendor_ID',
            'nsn_id': 'NSN_ID',
            'ia': 'IA',
            'fob': 'FOB',
            'order_qty': 'OrderQty',
            'ship_qty': 'ShipQty',
            'due_date': 'SubDueDate',
            'due_date_late': 'LateSDD',
            'supplier_due_date': 'VendorDueDate',
            'supplier_due_date_late': 'LateShipQDD',
            'ship_date': 'ShipDate',
            'ship_date_late': 'LateShip',
            'special_payment_terms_id': "CASE WHEN SPT = 1 THEN (SELECT TOP 1 id FROM contracts_specialpaymentterms WHERE code = SPT_Type) ELSE NULL END",
            'special_payment_terms_paid': 'SPT_Paid',
            'contract_value': 'ContractDol',
            'clin_value': 'SubPODol',
            'paid_amount': 'SubPaidDol',
            'paid_date': 'SubPaidDate',
            'wawf_payment': 'WAWFPaymentDol',
            'wawf_recieved': 'DatePayRecv',
            'wawf_invoice': 'WAWFInvoice',
            'plan_gross': 'PlanGrossDol',
            'planned_split': 'PlanSplit_per_PPIbid',
            'created_by_id': '(SELECT user_id FROM #UserMapping WHERE username = CreatedBy)',
            'created_on': 'CreatedOn',
            'modified_by_id': '(SELECT user_id FROM #UserMapping WHERE username = ModifiedBy)',
            'modified_on': 'ModifiedOn'
        }
        
        for django_field, sql_field in clin_mappings.items():
            self.stdout.write(f'  - {django_field}: {sql_field}')
            
        # Output JSON for easy reference
        mappings = {
            'clin': clin_mappings
        }
        
        self.stdout.write('\n' + self.style.SUCCESS('Mappings as JSON (for reference):'))
        self.stdout.write(json.dumps(mappings, indent=2)) 