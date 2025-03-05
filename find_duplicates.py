import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings')
django.setup()

from contracts.models import Contract
from django.db.models import Count

# Find duplicates
duplicates = Contract.objects.values('contract_number').annotate(count=Count('id')).filter(count__gt=1)

print("Found duplicate contract numbers:")
print("-" * 50)

for dup in duplicates:
    contract_number = dup['contract_number']
    contracts = Contract.objects.filter(contract_number=contract_number).order_by('created_on')
    print(f"\nContract number: {contract_number}")
    print("Instances:")
    for contract in contracts:
        print(f"  ID: {contract.id}")
        print(f"  Created: {contract.created_on}")
        print(f"  Modified: {contract.modified_on}")
        print(f"  Created by: {contract.created_by}")
        print("  " + "-" * 30) 