from django.core.management.base import BaseCommand
from django.db import connection
from users.models import AppPermission
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Cleans up NULL values and fixes data integrity issues in the AppPermission table'

    def handle(self, *args, **options):
        """Clean up AppPermission table"""
        self.stdout.write('Cleaning up AppPermission table...')
        
        # 1. Delete rows with NULL app_name or user_id
        before_count = AppPermission.objects.count()
        null_app_name = AppPermission.objects.filter(app_name__isnull=True).delete()
        null_user = AppPermission.objects.filter(user__isnull=True).delete()
        
        # 2. Run a direct SQL query to delete NULL rows (fallback)
        cursor = connection.cursor()
        cursor.execute("""
            DELETE FROM users_apppermission 
            WHERE app_name IS NULL OR user_id IS NULL
        """)
        
        # Check if any rows were deleted
        after_count = AppPermission.objects.count()
        deleted_count = before_count - after_count
        
        if deleted_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} invalid permission records"))
        else:
            self.stdout.write(self.style.SUCCESS("No invalid permission records found"))
        
        # 3. Fix duplicate permissions for the same user and app
        duplicates_fixed = 0
        
        # Find users with permissions
        users_with_permissions = set(AppPermission.objects.values_list('user_id', flat=True).distinct())
        
        for user_id in users_with_permissions:
            # Get all permissions for this user
            user_permissions = AppPermission.objects.filter(user_id=user_id)
            
            # Track which apps we've seen
            seen_apps = {}
            
            for perm in user_permissions:
                if perm.app_name_id in seen_apps:
                    # We've already seen this app for this user
                    # Keep the most recently updated one and delete the other
                    existing_perm = seen_apps[perm.app_name_id]
                    
                    if perm.id > existing_perm.id:  # Assuming higher ID = newer record
                        existing_perm.delete()
                        seen_apps[perm.app_name_id] = perm
                        duplicates_fixed += 1
                    else:
                        perm.delete()
                        duplicates_fixed += 1
                else:
                    seen_apps[perm.app_name_id] = perm
        
        if duplicates_fixed > 0:
            self.stdout.write(self.style.SUCCESS(f"Fixed {duplicates_fixed} duplicate permissions"))
        else:
            self.stdout.write(self.style.SUCCESS("No duplicate permissions found"))
            
        # Summary
        self.stdout.write("\nSummary:")
        self.stdout.write(f"- Initial permission count: {before_count}")
        self.stdout.write(f"- Final permission count: {AppPermission.objects.count()}")
        self.stdout.write(f"- Total records cleaned up: {deleted_count + duplicates_fixed}") 