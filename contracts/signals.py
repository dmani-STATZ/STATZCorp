from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from users.models import UserSetting

@receiver(post_save, sender=User)
def create_user_settings(sender, instance, created, **kwargs):
    if created:
        UserSetting.objects.create(user=instance) 