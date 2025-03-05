import os
import django
from django.db import transaction

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings')
django.setup()

from contracts.models import Contract

# List of IDs to delete based on our analysis
ids_to_delete = [3350, 21776, 16923, 2014, 2999]

try:
    with transaction.atomic():
        for contract_id in ids_to_delete:
            try:
                contract = Contract.objects.get(id=contract_id)
                print(f"Deleting contract ID {contract_id} (Contract number: {contract.contract_number})")
                contract.delete()
                print(f"Successfully deleted contract ID {contract_id}")
            except Contract.DoesNotExist:
                print(f"Contract ID {contract_id} not found")
            except Exception as e:
                print(f"Error deleting contract ID {contract_id}: {str(e)}")
                raise
    
    print("\nAll duplicates have been successfully removed.")
    print("You can now proceed with the migration.")
    
except Exception as e:
    print(f"\nAn error occurred: {str(e)}")
    print("No changes were made to the database (transaction rolled back)") 