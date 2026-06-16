from django.db import models
from django.conf import settings

class Campaign(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SCHEDULED', 'Scheduled'),
        ('SENDING', 'Sending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    name = models.CharField(max_length=255)
    subject_template = models.CharField(max_length=255, blank=True, null=True)
    body_template = models.TextField(blank=True, null=True)
    is_html_body = models.BooleanField(default=True, help_text="When True, body_template contains rich HTML from the editor. When False, plain text with auto-linking.")
    sender_email = models.EmailField(help_text="The email address this campaign is sent from")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # AI Generation
    ai_instruction = models.TextField(blank=True, null=True, help_text="Instruction prompt for the LLM")
    
    AI_STATUS_CHOICES = [
        ('IDLE', 'Idle'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    ai_status = models.CharField(max_length=20, choices=AI_STATUS_CHOICES, default='IDLE')
    
    # Follow-Ups
    follow_up_enabled = models.BooleanField(default=False)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class CampaignAttachment(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='campaign_attachments/')
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveIntegerField(help_text="File size in bytes")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name

    @property
    def file_size_display(self):
        """Human-readable file size."""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

class CampaignFollowUp(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='follow_ups')
    step_number = models.PositiveIntegerField()
    delay_days = models.PositiveIntegerField(help_text="Days to wait after the previous email was sent")
    subject_template = models.CharField(max_length=255, blank=True, null=True, help_text="Leave blank to use 'Re: original subject'")
    body_template = models.TextField()

    class Meta:
        ordering = ['step_number']
        unique_together = ('campaign', 'step_number')

    def __str__(self):
        return f"Step {self.step_number} (wait {self.delay_days} days)"

class CampaignRecipient(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('FAILED', 'Failed'),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='recipients')
    email = models.EmailField()
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    custom_data = models.JSONField(default=dict, blank=True, help_text="Additional merged columns from import")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    
    # Follow-Ups
    follow_up_active = models.BooleanField(default=True, help_text="Set to False if the recipient replied so they stop getting pings")
    current_followup_step = models.PositiveIntegerField(default=0)
    last_contact_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('campaign', 'email')

    def __str__(self):
        return self.email
