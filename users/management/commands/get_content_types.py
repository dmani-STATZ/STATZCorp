from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from contracts.models import Contract, Clin

class Command(BaseCommand):
    help = 'Gets ContentType IDs for Contract and Clin models'

    def handle(self, *args, **options):
        contract_content_type = ContentType.objects.get_for_model(Contract)
        clin_content_type = ContentType.objects.get_for_model(Clin)
        
        self.stdout.write(self.style.SUCCESS(f'Contract ContentType ID: {contract_content_type.id}'))
        self.stdout.write(self.style.SUCCESS(f'Clin ContentType ID: {clin_content_type.id}'))
        
        self.stdout.write('\nUse these IDs in your SQL migration script:')
        self.stdout.write(f'DECLARE @ContractContentTypeID INT = {contract_content_type.id};')
        self.stdout.write(f'DECLARE @ClinContentTypeID INT = {clin_content_type.id};') 