from django.contrib.auth import get_user_model
from django.db import models

class ActiveUserManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True).order_by('username')

# Add this to your User model if you want to keep the default manager as well
User = get_user_model()
User.active_objects = ActiveUserManager() 