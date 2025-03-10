from django.core.management.base import BaseCommand
from django.db import connection
import time

class Command(BaseCommand):
    help = 'Refreshes the materialized view for NSN data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed information about the refresh process',
        )

    def handle(self, *args, **options):
        verbose = options.get('verbose', False)
        
        self.stdout.write(self.style.SUCCESS('Starting NSN view refresh...'))
        
        try:
            start_time = time.time()
            
            with connection.cursor() as cursor:
                if verbose:
                    self.stdout.write('Executing stored procedure: dbo.sp_RefreshNsnView')
                cursor.execute("EXEC dbo.sp_RefreshNsnView")
            
            end_time = time.time()
            duration = end_time - start_time
            
            self.stdout.write(self.style.SUCCESS(f'NSN view refreshed successfully in {duration:.2f} seconds!'))
            
            # Get some stats about the refreshed view
            if verbose:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM nsn_view")
                    count = cursor.fetchone()[0]
                    self.stdout.write(f'Total records in NSN view: {count}')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error refreshing NSN view: {str(e)}'))
            self.stdout.write(self.style.WARNING('Common causes of this error:'))
            self.stdout.write(self.style.WARNING('1. The stored procedure dbo.sp_RefreshNsnView does not exist'))
            self.stdout.write(self.style.WARNING('2. The nsn_view table does not exist'))
            self.stdout.write(self.style.WARNING('3. Insufficient database permissions'))
            self.stdout.write(self.style.WARNING('\nTo fix this, run the setup script:'))
            self.stdout.write(self.style.WARNING('sqlcmd -S <server> -d <database> -U <username> -P <password> -i contracts/sql/setup_nsn_fulltext_and_job.sql')) 