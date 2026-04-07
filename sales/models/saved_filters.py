from django.conf import settings
from django.db import models


class SavedFilter(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='saved_filters',
    )
    name = models.CharField(max_length=100)
    filter_params = models.JSONField()
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dibbs_saved_filter'
        ordering = ['is_system', 'name']

    def __str__(self):
        return self.name
