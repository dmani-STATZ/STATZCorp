import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings')
django.setup()

from contracts.models import Contract
from django.db.models import Count

duplicate_pairs = [
    (3350, 5530, 'SPE4A7-12-M-0069'),
    (21751, 21776, 'SPE7M5-25-P-0799'),
    (16845, 16923, 'SPE7M5-22-P-8701'),
    (2013, 2014, 'SPE7L4-16-M-3463'),
    (2998, 2999, 'SPE5EC-17-C-F120')
]

print("Analyzing duplicate contracts:")
print("-" * 50)

for id1, id2, contract_number in duplicate_pairs:
    print(f"\nContract number: {contract_number}")
    
    contract1 = Contract.objects.get(id=id1)
    contract2 = Contract.objects.get(id=id2)
    
    clins1 = contract1.clin_set.count()
    clins2 = contract2.clin_set.count()
    
    notes1 = contract1.notes.count()
    notes2 = contract2.notes.count()
    
    print(f"\nContract 1 (ID: {id1}):")
    print(f"  CLINs: {clins1}")
    print(f"  Notes: {notes1}")
    print(f"  Created: {contract1.created_on}")
    print(f"  Modified: {contract1.modified_on}")
    
    print(f"\nContract 2 (ID: {id2}):")
    print(f"  CLINs: {clins2}")
    print(f"  Notes: {notes2}")
    print(f"  Created: {contract2.created_on}")
    print(f"  Modified: {contract2.modified_on}")
    
    print("\nRecommendation:")
    if clins1 > clins2 or notes1 > notes2:
        print(f"  Keep ID {id1}, update or delete ID {id2}")
    elif clins2 > clins1 or notes2 > notes1:
        print(f"  Keep ID {id2}, update or delete ID {id1}")
    else:
        print(f"  Both records have same amount of data. Suggest keeping the older one (ID {min(id1, id2)})")
    print("-" * 50) 