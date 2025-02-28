from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from contracts.models import Contract, Clin, Note
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Migrates notes from old ClinNote and ContractNote tables to the new ContentType-based Note model'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run the command without making any changes to the database',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry-run', False)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('Running in dry-run mode - no changes will be made'))
        
        # Get ContentTypes for Contract and Clin models
        contract_content_type = ContentType.objects.get_for_model(Contract)
        clin_content_type = ContentType.objects.get_for_model(Clin)
        
        self.stdout.write(f'Contract ContentType ID: {contract_content_type.id}')
        self.stdout.write(f'Clin ContentType ID: {clin_content_type.id}')
        
        # Use raw SQL to access the old tables that might not have models anymore
        from django.db import connection
        
        # Check if old tables exist
        with connection.cursor() as cursor:
            # Check if ContractNote table exists
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_name = 'contracts_contractnote'
            """)
            contract_notes_exist = cursor.fetchone()[0] > 0
            
            # Check if ClinNote table exists
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_name = 'contracts_clinnote'
            """)
            clin_notes_exist = cursor.fetchone()[0] > 0
        
        if not contract_notes_exist and not clin_notes_exist:
            self.stdout.write(self.style.ERROR('Old note tables do not exist. Nothing to migrate.'))
            return
        
        # Start transaction
        with transaction.atomic():
            # Migrate ContractNotes if the table exists
            if contract_notes_exist:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT id, contract_id, note, created_by, created_on
                        FROM contracts_contractnote
                    """)
                    contract_notes = cursor.fetchall()
                
                self.stdout.write(f'Found {len(contract_notes)} contract notes to migrate')
                
                for note_id, contract_id, note_text, created_by, created_on in contract_notes:
                    if not dry_run:
                        # Create new Note with ContentType
                        new_note = Note(
                            content_type=contract_content_type,
                            object_id=contract_id,
                            note=note_text,
                            created_by_id=None,  # Set to None if created_by was a string
                            created_on=created_on or timezone.now()
                        )
                        
                        # If created_by was a username string, we can't directly map it to a User ID
                        # You might need to handle this differently based on your data
                        
                        new_note.save()
                        self.stdout.write(f'Migrated ContractNote {note_id} to Note {new_note.id}')
                    else:
                        self.stdout.write(f'Would migrate ContractNote {note_id} for Contract {contract_id}')
            
            # Migrate ClinNotes if the table exists
            if clin_notes_exist:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT id, clin_id, note, created_by, created_on
                        FROM contracts_clinnote
                    """)
                    clin_notes = cursor.fetchall()
                
                self.stdout.write(f'Found {len(clin_notes)} CLIN notes to migrate')
                
                for note_id, clin_id, note_text, created_by, created_on in clin_notes:
                    if not dry_run:
                        # Create new Note with ContentType
                        new_note = Note(
                            content_type=clin_content_type,
                            object_id=clin_id,
                            note=note_text,
                            created_by_id=None,  # Set to None if created_by was a string
                            created_on=created_on or timezone.now()
                        )
                        
                        # If created_by was a username string, we can't directly map it to a User ID
                        # You might need to handle this differently based on your data
                        
                        new_note.save()
                        self.stdout.write(f'Migrated ClinNote {note_id} to Note {new_note.id}')
                    else:
                        self.stdout.write(f'Would migrate ClinNote {note_id} for CLIN {clin_id}')
        
        if not dry_run:
            self.stdout.write(self.style.SUCCESS('Successfully migrated notes to the new ContentType-based system'))
        else:
            self.stdout.write(self.style.SUCCESS('Dry run completed. No changes were made.')) 