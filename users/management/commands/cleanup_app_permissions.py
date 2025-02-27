from django.core.management.base import BaseCommand
from django.db import connection
from users.models import AppPermission, AppRegistry
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Cleans up duplicate app permission records and ensures data integrity'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Fix issues instead of just reporting them')

    def handle(self, *args, **options):
        """Clean up app permission records"""
        fix_mode = options['fix']
        self.stdout.write(f"Running in {'FIX' if fix_mode else 'REPORT ONLY'} mode")
        
        # Step 1: Find and list all users with permissions
        user_ids = AppPermission.objects.values_list('user_id', flat=True).distinct()
        users = User.objects.filter(id__in=user_ids)
        self.stdout.write(f"Found {users.count()} users with permission records")
        
        # Step 2: Check registry integrity
        app_names_in_permissions = AppPermission.objects.values_list('app_name', flat=True).distinct()
        self.stdout.write(f"Found {len(app_names_in_permissions)} unique app names in permission records")
        
        # Step 3: Fix duplicates for each user
        for user in users:
            self.stdout.write(f"\nChecking permissions for user: {user.username} (ID: {user.id})")
            
            # Get permissions for this user
            permissions = AppPermission.objects.filter(user=user)
            self.stdout.write(f"  Found {permissions.count()} permission records")
            
            # Find duplicates
            seen_apps = {}
            duplicates = []
            
            for perm in permissions:
                app_name = perm.app_name_id
                
                if app_name in seen_apps:
                    # Duplicate found
                    duplicates.append((seen_apps[app_name], perm))
                else:
                    seen_apps[app_name] = perm
            
            self.stdout.write(f"  Found {len(duplicates)} duplicate permission sets")
            
            # Fix duplicates if in fix mode
            if fix_mode and duplicates:
                for orig_perm, dup_perm in duplicates:
                    self.stdout.write(f"  - Removing duplicate: {dup_perm.id} (keeping {orig_perm.id})")
                    dup_perm.delete()
        
        # Step 4: Check database using SQL directly
        cursor = connection.cursor()
        cursor.execute("""
            SELECT 
                u.username, 
                ap.app_name_id, 
                COUNT(*) as count
            FROM 
                users_apppermission ap
                JOIN auth_user u ON ap.user_id = u.id
            GROUP BY 
                u.username, ap.app_name_id
            HAVING 
                COUNT(*) > 1
        """)
        
        remaining_duplicates = cursor.fetchall()
        
        if remaining_duplicates:
            self.stdout.write(self.style.WARNING(f"\nStill found {len(remaining_duplicates)} duplicate sets in database:"))
            
            for username, app_name, count in remaining_duplicates:
                self.stdout.write(f"  - User {username} has {count} permissions for app {app_name}")
                
                if fix_mode:
                    # Get all duplicates except the first one (which we'll keep)
                    cursor.execute("""
                        WITH Duplicates AS (
                            SELECT 
                                id,
                                ROW_NUMBER() OVER (PARTITION BY user_id, app_name_id ORDER BY id) as row_num
                            FROM 
                                users_apppermission
                            WHERE 
                                user_id = (SELECT id FROM auth_user WHERE username = %s)
                                AND app_name_id = %s
                        )
                        DELETE FROM users_apppermission
                        WHERE id IN (
                            SELECT id FROM Duplicates WHERE row_num > 1
                        )
                    """, [username, app_name])
                    
                    self.stdout.write(self.style.SUCCESS(f"    - Fixed by removing {count - 1} duplicate records"))
        else:
            self.stdout.write(self.style.SUCCESS("\nNo duplicates found in SQL check"))
            
        # Summary
        self.stdout.write("\nSummary:")
        self.stdout.write(f"- Total users with permissions: {users.count()}")
        self.stdout.write(f"- Total unique app names: {len(app_names_in_permissions)}")
        
        if fix_mode:
            self.stdout.write(self.style.SUCCESS("\nCleanup completed!"))
            self.stdout.write("Try using the admin interface again to modify permissions.")
        else:
            self.stdout.write(self.style.WARNING("\nRun with --fix to apply the changes")) 