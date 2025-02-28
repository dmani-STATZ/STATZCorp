from django.core.management.base import BaseCommand
from django.db import connection
from contracts.models import Contract, Buyer, ContractType, CanceledReason, SalesClass
import json

class Command(BaseCommand):
    help = 'Checks Contract table structure for migration'

    def handle(self, *args, **options):
        # Get Contract model fields
        contract_fields = [field.name for field in Contract._meta.get_fields() 
                          if not field.is_relation or field.one_to_one or field.many_to_one]
        
        # Get related model data
        buyers = list(Buyer.objects.values('id', 'description'))
        contract_types = list(ContractType.objects.values('id', 'description'))
        canceled_reasons = list(CanceledReason.objects.values('id', 'description'))
        sales_classes = list(SalesClass.objects.values('id', 'sales_team'))
        
        # Get Django table name
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name = 'contracts_contract'
            """)
            django_table = cursor.fetchone()
        
        # Output information
        self.stdout.write(self.style.SUCCESS(f'Django Contract Table: {django_table[0] if django_table else "Not found"}'))
        
        self.stdout.write('\n' + self.style.SUCCESS('Contract Model Fields:'))
        for field in contract_fields:
            self.stdout.write(f'  - {field}')
        
        self.stdout.write('\n' + self.style.SUCCESS('Buyers:'))
        for buyer in buyers:
            self.stdout.write(f'  - ID: {buyer["id"]}, Description: {buyer["description"]}')
        
        self.stdout.write('\n' + self.style.SUCCESS('Contract Types:'))
        for contract_type in contract_types:
            self.stdout.write(f'  - ID: {contract_type["id"]}, Description: {contract_type["description"]}')
        
        self.stdout.write('\n' + self.style.SUCCESS('Canceled Reasons:'))
        for reason in canceled_reasons:
            self.stdout.write(f'  - ID: {reason["id"]}, Description: {reason["description"]}')
        
        self.stdout.write('\n' + self.style.SUCCESS('Sales Classes:'))
        for sales_class in sales_classes:
            self.stdout.write(f'  - ID: {sales_class["id"]}, Sales Team: {sales_class["sales_team"]}')
        
        # Generate SQL field mappings
        self.stdout.write('\n' + self.style.SUCCESS('Suggested SQL Field Mappings:'))
        
        # Contract mappings
        contract_mappings = {
            'id': 'ID',
            'contract_number': 'ContractNum',
            'open': 'ContractOpen',
            'date_closed': 'DateClosed',
            'cancelled': 'ContractCancelled',
            'date_canceled': 'DateCancelled',
            'canceled_reason_id': 'ReasonCancelled',
            'po_number': 'PONumber',
            'tab_num': 'TabNum',
            'buyer_id': 'Buyer_ID',
            'contract_type_id': 'Type_ID',
            'award_date': '[Award Date]',
            'due_date': 'ContractDueDate',
            'due_date_late': 'LateShipCDD',
            'sales_class_id': 'SalesClass',
            'survey_date': 'SurveyDate',
            'survey_type': 'SurveyType',
            'assigned_user': 'AssignedUser',
            'assigned_date': 'AssignedDate',
            'nist': 'NIST',
            'files_url': 'URL',
            'reviewed': 'Reviewed',
            'reviewed_by': 'ReviewedBy',
            'reviewed_on': 'ReviewedOn',
            'created_by_id': '(SELECT user_id FROM #UserMapping WHERE username = CreatedBy)',
            'created_on': 'CreatedOn',
            'modified_by_id': '(SELECT user_id FROM #UserMapping WHERE username = ModifiedBy)',
            'modified_on': 'ModifiedOn'
        }
        
        for django_field, sql_field in contract_mappings.items():
            self.stdout.write(f'  - {django_field}: {sql_field}')
            
        # Output JSON for easy reference
        self.stdout.write('\n' + self.style.SUCCESS('Mappings as JSON (for reference):'))
        self.stdout.write(json.dumps(contract_mappings, indent=2)) 