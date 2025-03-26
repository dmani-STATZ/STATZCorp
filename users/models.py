from django.db import models
from django.contrib.auth.models import User
from django.apps import apps
import logging

# Create your models here.

class Announcement(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    posted_by = models.ForeignKey(User, on_delete=models.CASCADE)
    posted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class AppRegistry(models.Model):
    """Registry of all apps that can be managed in permissions"""
    app_name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App Registry"
        verbose_name_plural = "App Registries"

    def __str__(self):
        return f"{self.display_name} ({self.app_name})"
    
    @classmethod
    def get_active_apps(cls):
        """Get all active registered apps"""
        return cls.objects.filter(is_active=True)
    
    @classmethod
    def register_apps_from_system(cls):
        """Register all apps from the system"""
        from django.apps import apps
        excluded_apps = ['admin', 'auth', 'contenttypes', 'sessions', 'users']
        
        for app_config in apps.get_app_configs():
            # Skip Django internal and excluded apps
            if app_config.name.startswith('django.') or app_config.label in excluded_apps:
                continue
            
            # Get or create app registry
            cls.objects.update_or_create(
                app_name=app_config.label,
                defaults={
                    'display_name': getattr(app_config, 'verbose_name', app_config.label),
                    'is_active': True
                }
            )

class AppPermission(models.Model):
    """Model to store application permissions for users"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    app_name = models.ForeignKey(AppRegistry, on_delete=models.CASCADE)
    has_access = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = "App Permission"
        verbose_name_plural = "App Permissions"
        unique_together = ['user', 'app_name']
    
    def __str__(self):
        username = self.user.username if self.user else 'No User'
        try:
            app_name = self.app_name.app_name if self.app_name else 'No App'
        except AppRegistry.DoesNotExist:
            app_name = f'App ID: {self.app_name_id}'
        return f"{username} - {app_name} - {'✓' if self.has_access else '✗'}"
    
    @classmethod
    def get_permissions_for_user(cls, user):
        """Return a dictionary of app permissions for a user"""
        logger = logging.getLogger(__name__)
        
        logger.info(f"Getting permissions for user: {user} (ID: {user.id if user else 'None'})")
        
        if not user:
            logger.warning("No user provided, returning empty permissions")
            return {}
            
        # Get all permissions for this user
        user_permissions = cls.objects.filter(user=user)
        logger.info(f"Found {user_permissions.count()} permission records for user")
        
        # Convert to dictionary format {app_name: has_access}
        permissions = {}
        for perm in user_permissions:
            # Access the app_name field from the related AppRegistry
            app_name = perm.app_name.app_name
            permissions[app_name] = perm.has_access
            logger.info(f"Permission for app '{app_name}': {perm.has_access}")
            
        logger.info(f"Final permissions dictionary: {permissions}")
        return permissions

class UserSetting(models.Model):
    """Model to define available user settings"""
    SETTING_TYPES = [
        ('boolean', 'Boolean'),
        ('string', 'String'),
        ('integer', 'Integer'),
        ('json', 'JSON'),
    ]

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    setting_type = models.CharField(max_length=20, choices=SETTING_TYPES)
    default_value = models.TextField(blank=True)
    is_global = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Setting'
        verbose_name_plural = 'User Settings'
        ordering = ['name']

    def __str__(self):
        return self.name

class UserSettingState(models.Model):
    """Model to store user-specific setting states"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='setting_states')
    setting = models.ForeignKey(UserSetting, on_delete=models.CASCADE, related_name='user_states')
    value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Setting State'
        verbose_name_plural = 'User Setting States'
        unique_together = ['user', 'setting']
        indexes = [
            models.Index(fields=['user', 'setting']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.setting.name}"

    def get_value(self):
        """Convert the stored value to the appropriate type"""
        if self.setting.setting_type == 'boolean':
            return self.value.lower() == 'true'
        elif self.setting.setting_type == 'integer':
            return int(self.value) if self.value else 0
        elif self.setting.setting_type == 'json':
            import json
            return json.loads(self.value) if self.value else {}
        return self.value

    def set_value(self, value):
        """Convert the value to string before saving"""
        if self.setting.setting_type == 'boolean':
            self.value = str(value).lower()
        elif self.setting.setting_type == 'integer':
            self.value = str(int(value))
        elif self.setting.setting_type == 'json':
            import json
            self.value = json.dumps(value)
        else:
            self.value = str(value)
        self.save()