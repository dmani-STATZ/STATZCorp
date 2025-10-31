from datetime import timedelta
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.utils.text import slugify
import logging

User = get_user_model()

# Create your models here.

class Announcement(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    posted_by = models.ForeignKey(User, on_delete=models.CASCADE)
    posted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class PortalSection(models.Model):
    """Configurable portal section that can host documents, links, and tools."""

    VISIBILITY_CHOICES = [
        ('public', 'All authenticated users'),
        ('managers', 'Management and above'),
        ('private', 'Section editors only'),
    ]

    LAYOUT_CHOICES = [
        ('list', 'Resource list'),
        ('cards', 'Card grid'),
        ('kanban', 'Kanban / swimlanes'),
        ('timeline', 'Timeline'),
    ]

    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, help_text="Auto-generated from the title if left blank.")
    description = models.TextField(blank=True)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='public')
    layout = models.CharField(max_length=20, choices=LAYOUT_CHOICES, default='list')
    configuration = models.JSONField(default=dict, blank=True, help_text="UI preferences and filters for this section.")
    icon = models.CharField(max_length=60, blank=True, help_text="Heroicons name or custom CSS class.")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_pinned = models.BooleanField(default=False)
    allow_uploads = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='created_portal_sections')
    editors = models.ManyToManyField(User, blank=True, related_name='editable_portal_sections')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', 'order', 'title']
        verbose_name = 'Portal Section'
        verbose_name_plural = 'Portal Sections'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)[:150] or 'section'
            candidate = base_slug
            suffix = 1
            while PortalSection.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base_slug}-{suffix}"
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def is_visible_to(self, user):
        """Determine if a user should see this section."""
        if not self.is_active:
            return False
        if self.visibility == 'public':
            return True
        if not user or not user.is_authenticated:
            return False
        if self.visibility == 'managers':
            return getattr(user, 'is_manager', False) or user.is_staff or user.is_superuser
        return user.is_superuser or self.editors.filter(pk=user.pk).exists()


class PortalResource(models.Model):
    """Files, links, or embedded tools attached to a portal section."""

    RESOURCE_TYPE_CHOICES = [
        ('file', 'File upload'),
        ('link', 'External link'),
        ('embed', 'Embedded content'),
    ]

    section = models.ForeignKey(PortalSection, on_delete=models.CASCADE, related_name='resources')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    resource_type = models.CharField(max_length=20, choices=RESOURCE_TYPE_CHOICES, default='file')
    file = models.FileField(upload_to='portal/resources/%Y/%m/%d', blank=True, null=True)
    external_url = models.URLField(blank=True)
    embed_code = models.TextField(blank=True, help_text="Optional iframe or script for embedded resources.")
    icon = models.CharField(max_length=60, blank=True)
    tags = models.JSONField(default=list, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='uploaded_portal_resources')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-is_featured', 'title']

    def __str__(self):
        return f"{self.title} ({self.section.title})"

    def clean(self):
        super().clean()
        if self.resource_type == 'file' and not self.file:
            raise ValidationError("File uploads require a file.")
        if self.resource_type == 'link' and not self.external_url:
            raise ValidationError("Links require an external URL.")
        if self.resource_type == 'embed' and not self.embed_code:
            raise ValidationError("Embedded resources require embed code.")

    def get_absolute_url(self):
        if self.resource_type == 'file' and self.file:
            return self.file.url
        if self.resource_type == 'link':
            return self.external_url
        return ''


class WorkCalendarTask(models.Model):
    """Task item that can graduate into a scheduled calendar block."""

    STATUS_CHOICES = [
        ('backlog', 'Backlog'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    IMPORTANCE_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    ENERGY_CHOICES = [
        ('light', 'Light'),
        ('moderate', 'Moderate'),
        ('deep', 'Deep focus'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calendar_tasks')
    due_date = models.DateField(null=True, blank=True)
    importance = models.CharField(max_length=10, choices=IMPORTANCE_CHOICES, default='medium')
    energy_required = models.CharField(max_length=10, choices=ENERGY_CHOICES, default='moderate')
    estimated_minutes = models.PositiveIntegerField(default=30)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='backlog')
    source_app = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', '-importance', 'due_date', 'title']

    def __str__(self):
        return self.title

    @property
    def is_completed(self):
        return self.status == 'completed'


class WorkCalendarEvent(models.Model):
    """Context aware work calendar event with priority and energy mapping."""

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    ENERGY_CHOICES = WorkCalendarTask.ENERGY_CHOICES

    EVENT_KIND_CHOICES = [
        ('meeting', 'Meeting'),
        ('focus', 'Focus block'),
        ('one_on_one', '1:1'),
        ('training', 'Training'),
        ('travel', 'Travel'),
        ('personal', 'Personal placeholder'),
        ('break', 'Micro-break'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=EVENT_KIND_CHOICES, default='meeting')
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    organizer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='organized_calendar_events')
    section = models.ForeignKey(PortalSection, null=True, blank=True, on_delete=models.SET_NULL, related_name='calendar_events')
    location = models.CharField(max_length=255, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    energy_required = models.CharField(max_length=10, choices=ENERGY_CHOICES, default='moderate')
    focus_block = models.BooleanField(default=False)
    focus_reason = models.CharField(max_length=255, blank=True)
    predicted_attendance = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
        help_text="Probability (0-1) that the meeting will hit quorum."
    )
    requires_travel = models.BooleanField(default=False)
    smart_notes = models.JSONField(default=dict, blank=True)
    tasks = models.ManyToManyField(WorkCalendarTask, blank=True, related_name='scheduled_events')
    is_private = models.BooleanField(default=False)
    privacy_label = models.CharField(max_length=120, blank=True, help_text="Display text for shared calendars when event is private.")
    source_system = models.CharField(max_length=100, blank=True)
    source_identifier = models.CharField(max_length=255, blank=True)
    created_via_nlp = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_at']
        verbose_name = 'Work Calendar Event'
        verbose_name_plural = 'Work Calendar Events'
        indexes = [
            models.Index(fields=['start_at', 'end_at']),
            models.Index(fields=['organizer', 'start_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.start_at:%Y-%m-%d %H:%M})"

    def clean(self):
        super().clean()
        if self.end_at <= self.start_at:
            raise ValidationError("Event end time must be after start time.")

    @property
    def duration_minutes(self):
        return int((self.end_at - self.start_at).total_seconds() / 60)

    def get_effective_title(self):
        """Respect privacy placeholders when rendering."""
        if self.is_private and self.privacy_label:
            return self.privacy_label
        return self.title


class EventAttendance(models.Model):
    """Track attendance behaviour to fuel contextual insights."""

    STATUS_CHOICES = [
        ('invited', 'Invited'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('tentative', 'Tentative'),
        ('no_show', 'No show'),
        ('attended', 'Attended'),
    ]

    event = models.ForeignKey(WorkCalendarEvent, on_delete=models.CASCADE, related_name='attendance_records')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calendar_attendance')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='invited')
    responded_at = models.DateTimeField(null=True, blank=True)
    attendance_marked_at = models.DateTimeField(null=True, blank=True)
    confidence_score = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
        help_text="Probability the user will show up based on historical data."
    )
    auto_detected = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('event', 'user')
        ordering = ['event', 'user__username']

    def __str__(self):
        return f"{self.user} -> {self.event} [{self.status}]"


class EventReminder(models.Model):
    """Smart reminders tied to the event timeline."""

    REMINDER_TYPE_CHOICES = [
        ('standard', 'Standard'),
        ('travel', 'Travel time'),
        ('buffer', 'Recovery buffer'),
        ('wellness', 'Micro-break / wellness'),
    ]

    event = models.ForeignKey(WorkCalendarEvent, on_delete=models.CASCADE, related_name='reminders')
    reminder_type = models.CharField(max_length=20, choices=REMINDER_TYPE_CHOICES, default='standard')
    offset_minutes = models.IntegerField(default=15)
    message = models.CharField(max_length=255, blank=True)
    smart_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['offset_minutes']

    def __str__(self):
        return f"{self.get_reminder_type_display()} reminder for {self.event}"

    @property
    def scheduled_for(self):
        return self.event.start_at - timedelta(minutes=self.offset_minutes)


class NaturalLanguageScheduleRequest(models.Model):
    """Store natural language scheduling prompts and parsing results."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('parsed', 'Parsed'),
        ('scheduled', 'Scheduled'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='nlp_schedule_requests')
    raw_text = models.TextField()
    normalized_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    interpreted_start = models.DateTimeField(null=True, blank=True)
    interpreted_end = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    attendees = models.JSONField(default=list, blank=True)
    associated_event = models.ForeignKey(WorkCalendarEvent, null=True, blank=True, on_delete=models.SET_NULL, related_name='nlp_requests')
    diagnostics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Natural Language Scheduling Request'

    def __str__(self):
        return f"NLP request by {self.user} on {self.created_at:%Y-%m-%d}"

    def mark_failed(self, message, diagnostics=None):
        self.status = 'failed'
        self.error_message = message
        if diagnostics is not None:
            self.diagnostics = diagnostics
        self.save(update_fields=['status', 'error_message', 'diagnostics', 'updated_at'])

    def mark_scheduled(self, event, diagnostics=None):
        self.status = 'scheduled'
        self.associated_event = event
        if diagnostics is not None:
            self.diagnostics = diagnostics
        self.save(update_fields=['status', 'associated_event', 'diagnostics', 'updated_at'])


class CalendarAnalyticsSnapshot(models.Model):
    """Aggregated analytics to power the sanity dashboard."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calendar_analytics')
    range_start = models.DateField()
    range_end = models.DateField()
    meeting_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    focus_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    ghost_meeting_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))],
    )
    context_switches = models.PositiveIntegerField(default=0)
    wellness_breaks_inserted = models.PositiveIntegerField(default=0)
    suggestions = models.TextField(blank=True)
    recommendation_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-range_end']
        unique_together = ('user', 'range_start', 'range_end')

    def __str__(self):
        return f"{self.user} analytics {self.range_start} - {self.range_end}"


class ScheduledMicroBreak(models.Model):
    """Explicit record of the micro-breaks inserted between events."""

    INSERTION_MODE_CHOICES = [
        ('auto', 'Automatic'),
        ('suggested', 'Suggested'),
        ('manual', 'Manual'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scheduled_microbreaks')
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    label = models.CharField(max_length=120, default='Micro-break')
    insertion_mode = models.CharField(max_length=10, choices=INSERTION_MODE_CHOICES, default='auto')
    related_event = models.ForeignKey(WorkCalendarEvent, null=True, blank=True, on_delete=models.SET_NULL, related_name='microbreaks')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_at']

    def __str__(self):
        return f"{self.label} ({self.start_at:%H:%M})"



class UserCompanyMembership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='company_memberships')
    company = models.ForeignKey('contracts.Company', on_delete=models.CASCADE, related_name='user_memberships')
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'company')
        verbose_name = 'User Company Membership'
        verbose_name_plural = 'User Company Memberships'

    def __str__(self):
        return f"{self.user} -> {self.company}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            UserCompanyMembership.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)
        elif not UserCompanyMembership.objects.filter(user=self.user, is_default=True).exists():
            UserCompanyMembership.objects.filter(pk=self.pk).update(is_default=True)

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
        return f"{username} - {app_name} - {'granted' if self.has_access else 'denied'}"
    
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
    """Stores the actual value of a UserSetting for a specific User."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='setting_states')
    setting = models.ForeignKey(UserSetting, on_delete=models.CASCADE, related_name='states')
    value = models.TextField(blank=True, null=True)  # Store value based on setting type

    class Meta:
        unique_together = ('user', 'setting')
        verbose_name = "User Setting State"
        verbose_name_plural = "User Setting States"

    def __str__(self):
        return f"{self.user.username} - {self.setting.name}: {self.value}"

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

class UserOAuthToken(models.Model):
    """Stores OAuth tokens for users."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='oauth_token')
    provider = models.CharField(max_length=50, default='microsoft') # Identifies the OAuth provider
    access_token = models.TextField()
    refresh_token = models.TextField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True) # Store actual datetime when the access token expires
    updated_at = models.DateTimeField(auto_now=True) # Track when the token was last updated

    class Meta:
        verbose_name = "User OAuth Token"
        verbose_name_plural = "User OAuth Tokens"
        constraints = [
            models.UniqueConstraint(fields=['user', 'provider'], name='unique_user_provider_token')
        ]

    def __str__(self):
        return f"{self.user.username} - {self.provider} Token"

    @property
    def is_expired(self):
        """Check if the access token is expired."""
        if not self.expires_at:
            return False # Cannot determine expiry
        return timezone.now() >= self.expires_at

class SystemMessage(models.Model):
    """Model for storing system-wide notifications."""
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical')
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='system_messages')
    title = models.CharField(max_length=200)
    message = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    source_app = models.CharField(max_length=50, help_text="The app that generated this message")
    source_model = models.CharField(max_length=50, help_text="The model that generated this message")
    source_id = models.CharField(max_length=50, help_text="The ID of the record that generated this message")
    action_url = models.CharField(max_length=255, blank=True, help_text="URL to relevant action/page")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'read_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
    def mark_as_read(self):
        """Mark the message as read."""
        self.read_at = timezone.now()
        self.save()
    
    @property
    def is_read(self):
        """Check if the message has been read."""
        return self.read_at is not None
    
    @classmethod
    def get_unread_count(cls, user):
        """Get count of unread messages for a user."""
        return cls.objects.filter(user=user, read_at__isnull=True).count()
    
    @classmethod
    def create_message(cls, user, title, message, **kwargs):
        """Create a new system message."""
        return cls.objects.create(
            user=user,
            title=title,
            message=message,
            **kwargs
        )
