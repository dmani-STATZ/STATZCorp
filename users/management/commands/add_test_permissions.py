from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from users.models import AppRegistry, AppPermission
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Adds test permissions for a specified user'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username to add permissions for')

    def handle(self, *args, **options):
        """Add test permissions for a user"""
        username = options['username']
        self.stdout.write(f'Adding test permissions for user: {username}')
        
        try:
            # Get the user
            user = User.objects.get(username=username)
            self.stdout.write(self.style.SUCCESS(f"Found user: {user.username} (ID: {user.id})"))
            
            # Get all registered apps
            registered_apps = AppRegistry.get_active_apps()
            self.stdout.write(f"Found {registered_apps.count()} registered apps")
            
            # Add permissions for each app
            for app in registered_apps:
                # Set all apps to have access
                perm, created = AppPermission.objects.update_or_create(
                    user=user,
                    app_name=app.app_name,
                    defaults={'has_access': True}
                )
                
                # Log the result
                if created:
                    self.stdout.write(f"Created new permission: {perm}")
                else:
                    self.stdout.write(f"Updated permission: {perm}")
            
            # Verify permissions were created
            permissions = AppPermission.objects.filter(user=user)
            self.stdout.write(self.style.SUCCESS(f"Total permissions for {username}: {permissions.count()}"))
            
            # List all permissions
            for perm in permissions:
                self.stdout.write(f"- {perm}")
                
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User '{username}' not found!"))
            return 