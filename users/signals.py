# users/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import AppPermission
from django.apps import apps

@receiver(post_save, sender=User)
def create_default_permissions(sender, instance, created, **kwargs):
    if created:
        for app_config in apps.get_app_configs():
            if app_config.name != 'users' and app_config.name != 'admin' and app_config.name != 'auth' and app_config.name != 'contenttypes' and app_config.name != 'sessions': #add any other apps you do not want to add permissions for.
                AppPermission.objects.create(user=instance, app_name=app_config.name, has_access=False)