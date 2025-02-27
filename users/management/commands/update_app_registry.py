from django.core.management.base import BaseCommand
from users.models import AppRegistry
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Updates the app registry with all installed apps'

    def handle(self, *args, **options):
        """Register all apps from the system"""
        self.stdout.write('Updating app registry...')
        
        # Register apps from system
        before_count = AppRegistry.objects.count()
        AppRegistry.register_apps_from_system()
        after_count = AppRegistry.objects.count()
        
        # Log results
        new_apps = after_count - before_count
        if new_apps > 0:
            self.stdout.write(self.style.SUCCESS(f'Added {new_apps} new apps to registry'))
        else:
            self.stdout.write(self.style.SUCCESS('App registry is up to date'))
            
        # List all registered apps
        self.stdout.write('\nRegistered apps:')
        for app in AppRegistry.objects.all().order_by('app_name'):
            status = 'ACTIVE' if app.is_active else 'INACTIVE'
            self.stdout.write(f'- {app.display_name} ({app.app_name}) [{status}]') 