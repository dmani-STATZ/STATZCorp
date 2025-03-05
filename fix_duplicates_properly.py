import os
import django
import sys

# Set up Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings')
django.setup()

from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from contracts.models import Contract, Clin

# Pairs of (keep_id, delete_id, contract_number)
contract_pairs = [
    (5530, 3350, 'SPE4A7-12-M-0069'),
    (21751, 21776, 'SPE7M5-25-P-0799'),
    (16845, 16923, 'SPE7M5-22-P-8701'),
    (2013, 2014, 'SPE7L4-16-M-3463'),
    (2998, 2999, 'SPE5EC-17-C-F120')
]

def check_clin_duplicates(contract):
    """Check for duplicate CLINs within a contract"""
    clins = contract.clin_set.all()
    seen_clins = {}
    duplicates = []
    
    for clin in clins:
        key = (clin.clin_type_id if clin.clin_type else None,
               clin.supplier_id if clin.supplier else None,
               clin.nsn_id if clin.nsn else None,
               clin.order_qty)
        
        if key in seen_clins:
            duplicates.append((seen_clins[key], clin))
        else:
            seen_clins[key] = clin
    
    return duplicates

try:
    with transaction.atomic():
        for keep_id, delete_id, contract_number in contract_pairs:
            print(f"\nProcessing contract number: {contract_number}")
            
            try:
                keep_contract = Contract.objects.get(id=keep_id)
                delete_contract = Contract.objects.get(id=delete_id)
                
                # Transfer CLINs
                clins_to_move = delete_contract.clin_set.all()
                print(f"Moving {clins_to_move.count()} CLINs from ID {delete_id} to ID {keep_id}")
                
                for clin in clins_to_move:
                    print(f"  Moving CLIN {clin.id}")
                    clin.contract = keep_contract
                    clin.save()
                
                # Transfer Notes
                notes_to_move = delete_contract.notes.all()
                print(f"Moving {notes_to_move.count()} Notes from ID {delete_id} to ID {keep_id}")
                
                contract_content_type = ContentType.objects.get_for_model(Contract)
                for note in notes_to_move:
                    print(f"  Moving Note {note.id}")
                    note.content_type = contract_content_type
                    note.object_id = keep_contract.id
                    note.save()
                
                # Check for duplicate CLINs in the kept contract
                duplicate_clins = check_clin_duplicates(keep_contract)
                if duplicate_clins:
                    print(f"\nFound {len(duplicate_clins)} duplicate CLIN pairs in contract {keep_contract.id}:")
                    for clin1, clin2 in duplicate_clins:
                        print(f"\nDuplicate CLINs found:")
                        print(f"CLIN 1 (ID: {clin1.id}):")
                        print(f"  Type: {clin1.clin_type}")
                        print(f"  Supplier: {clin1.supplier}")
                        print(f"  NSN: {clin1.nsn}")
                        print(f"  Order Qty: {clin1.order_qty}")
                        print(f"  Notes: {clin1.notes.count()}")
                        
                        print(f"\nCLIN 2 (ID: {clin2.id}):")
                        print(f"  Type: {clin2.clin_type}")
                        print(f"  Supplier: {clin2.supplier}")
                        print(f"  NSN: {clin2.nsn}")
                        print(f"  Order Qty: {clin2.order_qty}")
                        print(f"  Notes: {clin2.notes.count()}")
                        
                        # Keep the CLIN with more notes or the older one if equal
                        if clin1.notes.count() >= clin2.notes.count():
                            print(f"  Keeping CLIN {clin1.id}, deleting CLIN {clin2.id}")
                            # Move any notes from clin2 to clin1
                            clin_content_type = ContentType.objects.get_for_model(Clin)
                            for note in clin2.notes.all():
                                note.content_type = clin_content_type
                                note.object_id = clin1.id
                                note.save()
                            clin2.delete()
                        else:
                            print(f"  Keeping CLIN {clin2.id}, deleting CLIN {clin1.id}")
                            # Move any notes from clin1 to clin2
                            clin_content_type = ContentType.objects.get_for_model(Clin)
                            for note in clin1.notes.all():
                                note.content_type = clin_content_type
                                note.object_id = clin2.id
                                note.save()
                            clin1.delete()
                
                # Now delete the duplicate contract
                print(f"Deleting contract ID {delete_id}")
                delete_contract.delete()
                print(f"Successfully processed contract {contract_number}")
                
            except Contract.DoesNotExist as e:
                print(f"One of the contracts not found: {str(e)}")
            except Exception as e:
                print(f"Error processing contract {contract_number}: {str(e)}")
                raise
    
    print("\nAll duplicates have been successfully processed.")
    print("CLINs and Notes have been transferred to the kept contracts.")
    print("Duplicate contracts have been deleted.")
    print("Duplicate CLINs within contracts have been resolved.")
    print("You can now proceed with the migration.")
    
except Exception as e:
    print(f"\nAn error occurred: {str(e)}")
    print("No changes were made to the database (transaction rolled back)") 