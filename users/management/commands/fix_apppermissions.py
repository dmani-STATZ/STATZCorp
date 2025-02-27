from django.core.management.base import BaseCommand
from django.db import connection
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Ensures the AppPermission table has correct constraints and data'

    def handle(self, *args, **options):
        """Fix AppPermission table"""
        self.stdout.write('Checking AppPermission table structure...')
        
        cursor = connection.cursor()
        
        # Check if app_name column allows NULL values
        cursor.execute("""
            SELECT 
                COLUMN_NAME, 
                IS_NULLABLE 
            FROM 
                INFORMATION_SCHEMA.COLUMNS 
            WHERE 
                TABLE_NAME = 'users_apppermission' 
                AND COLUMN_NAME = 'app_name'
        """)
        
        column_info = cursor.fetchone()
        if column_info and column_info[1] == 'YES':
            self.stdout.write(self.style.WARNING("app_name column allows NULL values - fixing..."))
            
            # Fix nullable constraint
            cursor.execute("""
                ALTER TABLE users_apppermission
                ALTER COLUMN app_name NVARCHAR(100) NOT NULL
            """)
            connection.commit()
            self.stdout.write(self.style.SUCCESS("app_name column updated to NOT NULL"))
        else:
            self.stdout.write(self.style.SUCCESS("app_name column already correctly configured"))
            
        # Check for NULL app_name values
        cursor.execute("""
            SELECT COUNT(*) FROM users_apppermission WHERE app_name IS NULL
        """)
        
        null_count = cursor.fetchone()[0]
        if null_count > 0:
            self.stdout.write(self.style.WARNING(f"Found {null_count} records with NULL app_name - deleting..."))
            
            # Delete records with NULL app_name
            cursor.execute("""
                DELETE FROM users_apppermission WHERE app_name IS NULL
            """)
            connection.commit()
            self.stdout.write(self.style.SUCCESS(f"Deleted {null_count} invalid records"))
        else:
            self.stdout.write(self.style.SUCCESS("No records with NULL app_name found"))
            
        # Count existing permissions
        cursor.execute("""
            SELECT COUNT(*) FROM users_apppermission
        """)
        
        permission_count = cursor.fetchone()[0]
        self.stdout.write(self.style.SUCCESS(f"Current permission count: {permission_count}"))
        
        # Check unique constraint
        cursor.execute("""
            IF NOT EXISTS (
                SELECT * FROM sys.indexes 
                WHERE name = 'users_apppermission_user_id_app_name_unique' 
                AND object_id = OBJECT_ID('users_apppermission')
            )
            BEGIN
                ALTER TABLE users_apppermission
                ADD CONSTRAINT users_apppermission_user_id_app_name_unique UNIQUE (user_id, app_name);
                SELECT 'Added unique constraint on user_id and app_name';
            END
            ELSE
            BEGIN
                SELECT 'Unique constraint already exists';
            END
        """)
        
        result = cursor.fetchone()
        if result:
            self.stdout.write(self.style.SUCCESS(result[0])) 