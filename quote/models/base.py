"""
Shared abstract base for quote-owned models.

Redefined locally on purpose: every app in this repo declares its own
AuditModel with app-scoped related_names. Do not cross-import another app's.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class AuditModel(models.Model):
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_%(class)s_created',
    )
    created_on = models.DateTimeField(default=timezone.now)
    modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_%(class)s_modified',
    )
    modified_on = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.id:
            self.created_on = timezone.now()
        self.modified_on = timezone.now()
        super().save(*args, **kwargs)
