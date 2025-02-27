from django.core.management.base import BaseCommand
from django.db import connection
from users.models import AppRegistry
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Fixes the AppRegistry table in SQL Server'

    def handle(self, *args, **options):
        """Fix AppRegistry table"""
        self.stdout.write('Checking AppRegistry table...')
        
        cursor = connection.cursor()
        
        # Check if table exists
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[users_appregistry]') AND type in (N'U'))
            BEGIN
                CREATE TABLE [dbo].[users_appregistry] (
                    [id] [int] IDENTITY(1,1) NOT NULL,
                    [app_name] [nvarchar](100) NOT NULL,
                    [display_name] [nvarchar](200) NOT NULL,
                    [is_active] [bit] NOT NULL,
                    [created_at] [datetime2](7) NOT NULL,
                    [updated_at] [datetime2](7) NOT NULL,
                    CONSTRAINT [PK_users_appregistry] PRIMARY KEY CLUSTERED ([id] ASC),
                    CONSTRAINT [users_appregistry_app_name_unique] UNIQUE NONCLUSTERED ([app_name] ASC)
                )
                
                SELECT 'Table users_appregistry created.'
            END
            ELSE
            BEGIN
                SELECT 'Table users_appregistry already exists.'
            END
        """)
        
        result = cursor.fetchone()
        if result:
            self.stdout.write(self.style.SUCCESS(result[0]))
        
        connection.commit()
        
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