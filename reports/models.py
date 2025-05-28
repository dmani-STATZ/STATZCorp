from django.db import models
from django.contrib.auth import get_user_model
from django.utils.text import slugify
import uuid

User = get_user_model()

class ReportRequest(models.Model):
    """Model for storing user report requests."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='report_requests')
    request_text = models.TextField(help_text="Describe what you need in this report")
    generated_name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_to = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='assigned_reports'
    )
    
    def save(self, *args, **kwargs):
        if not self.generated_name:
            # Generate a name based on first 5 words of request
            words = self.request_text.split()[:5]
            name = ' '.join(words)
            self.generated_name = f"{slugify(name)}-{str(self.id)[:8]}"
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.generated_name

class Report(models.Model):
    """Model for storing completed reports."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report_request = models.OneToOneField(
        ReportRequest, 
        on_delete=models.CASCADE,
        related_name='completed_report'
    )
    sql_query = models.TextField(help_text="The SQL query that generates this report")
    description = models.TextField(help_text="Description of what this report shows", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Report for {self.report_request.generated_name}"

class ReportChange(models.Model):
    """Model for tracking requested changes to reports."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='change_requests')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    change_text = models.TextField(help_text="Describe what changes you need")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Change request for {self.report.report_request.generated_name}"
