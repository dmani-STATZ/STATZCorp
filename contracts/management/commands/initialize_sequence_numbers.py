import logging
from django.core.management.base import BaseCommand
from django.db.models import Max
from contracts.models import Contract, SequenceNumber

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Initialize sequence numbers based on existing contracts'

    def handle(self, *args, **options):
        self.stdout.write('Starting sequence number initialization...')
        
        # Find the maximum PO number and TAB number from existing contracts
        max_po_number = Contract.objects.aggregate(Max('po_number'))['po_number__max']
        max_tab_num = Contract.objects.aggregate(Max('tab_num'))['tab_num__max']
        
        # Convert to integers if they exist, otherwise default to 10000
        try:
            max_po_number = int(max_po_number) if max_po_number else 10000
        except (ValueError, TypeError):
            self.stdout.write(self.style.WARNING(f'Could not convert PO number "{max_po_number}" to integer. Using 10000.'))
            max_po_number = 10000
            
        try:
            max_tab_num = int(max_tab_num) if max_tab_num else 10000
        except (ValueError, TypeError):
            self.stdout.write(self.style.WARNING(f'Could not convert TAB number "{max_tab_num}" to integer. Using 10000.'))
            max_tab_num = 10000
        
        # Create or update the sequence number record
        sequence, created = SequenceNumber.objects.get_or_create(
            id=1,
            defaults={
                'po_number': max_po_number + 1,
                'tab_number': max_tab_num + 1
            }
        )
        
        if not created:
            # Update the values if they're lower than what we found
            if sequence.po_number <= max_po_number:
                sequence.po_number = max_po_number + 1
                
            if sequence.tab_number <= max_tab_num:
                sequence.tab_number = max_tab_num + 1
                
            sequence.save()
            
        self.stdout.write(self.style.SUCCESS(
            f'Sequence numbers initialized: PO number = {sequence.po_number}, '
            f'TAB number = {sequence.tab_number}'
        )) 