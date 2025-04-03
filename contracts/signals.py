from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User

# Signal removed as it's now handled in users/signals.py 