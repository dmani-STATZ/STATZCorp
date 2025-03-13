from django.core.management.base import BaseCommand
from django.db import connection
import time

class Command(BaseCommand):
    help = 'This command is deprecated - the NSN view is now a true database view that refreshes automatically'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed information about the view',
        )

    def handle(self, *args, **options):
        verbose = options.get('verbose', False)
        
        self.stdout.write(self.style.WARNING('DEPRECATED: The NSN view is now a true database view that refreshes automatically'))
        
        try:
            # Just report some stats about the view
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM nsn_view")
                count = cursor.fetchone()[0]
                self.stdout.write(self.style.SUCCESS(f'Total records in NSN view: {count}'))
                
                if verbose:
                    self.stdout.write('Getting sample data from the view:')
                    cursor.execute("SELECT TOP 5 id, nsn_code, description, clin_count FROM nsn_view ORDER BY clin_count DESC")
                    rows = cursor.fetchall()
                    for row in rows:
                        self.stdout.write(f'NSN {row[1]}: {row[2][:30]}... (Used in {row[3]} CLINs)')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error accessing NSN view: {str(e)}'))
            self.stdout.write(self.style.WARNING('Common causes of this error:'))
            self.stdout.write(self.style.WARNING('1. The nsn_view database view does not exist'))
            self.stdout.write(self.style.WARNING('2. Insufficient database permissions'))
            self.stdout.write(self.style.WARNING('\nTo fix this, run the setup script:'))
            self.stdout.write(self.style.WARNING('sqlcmd -S <server> -d <database> -U <username> -P <password> -i create_nsn_view.sql')) 