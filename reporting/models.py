from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import User

User = get_user_model()

def get_default_list():
    return list()

def get_default_dict():
    return dict()

# Create your models here.
class SavedReport(models.Model):
    name = models.CharField(max_length=200)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    selected_tables = models.JSONField(default=get_default_list, help_text='List of selected table names')
    selected_fields = models.JSONField(default=get_default_dict, help_text='Dictionary mapping table names to their selected fields')
    filters = models.JSONField(default=get_default_list, help_text='Filter criteria for each table')
    sort_by = models.JSONField(default=get_default_dict, help_text='Sort by configuration for each table')
    group_by = models.JSONField(default=get_default_dict, help_text='Group by configuration for each table')
    aggregations = models.JSONField(
        default=get_default_dict, 
        help_text='Aggregation settings for numeric fields. Format: {"field_path": {"type": "sum|avg|min|max|count", "label": "Custom Label"}}'
    )
    sort_direction = models.CharField(max_length=4, choices=[('asc', 'Ascending'), ('desc', 'Descending')])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name
