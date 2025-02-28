# users/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import AppPermission, AppRegistry
from django.apps import apps
import logging

logger = logging.getLogger(__name__)

# Signal handler commented out - no longer automatically creating permissions for new users
"""
@receiver(post_save, sender=User)
def create_default_permissions(sender, instance, created, **kwargs):
    if created:
        logger.info(f"Creating default permissions for new user: {instance.username}")
        for app_config in apps.get_app_configs():
            if app_config.name != 'users' and app_config.name != 'admin' and app_config.name != 'auth' and app_config.name != 'contenttypes' and app_config.name != 'sessions': #add any other apps you do not want to add permissions for.
                try:
                    # Get or create the AppRegistry instance for this app
                    app_registry, created = AppRegistry.objects.get_or_create(
                        app_name=app_config.name,
                        defaults={
                            'display_name': getattr(app_config, 'verbose_name', app_config.name),
                            'is_active': True
                        }
                    )
                    
                    # Create the permission using the AppRegistry instance
                    AppPermission.objects.create(
                        user=instance, 
                        app_name=app_registry, 
                        has_access=False
                    )
                    logger.info(f"Created permission for app: {app_config.name}")
                except Exception as e:
                    logger.error(f"Error creating permission for app {app_config.name}: {e}")
"""