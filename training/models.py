import calendar
import uuid

from django.db import models
from django.contrib.auth.models import User  # Import the User model
from django.utils import timezone
from django.utils.text import slugify


def add_months(source_date, months):
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, calendar.monthrange(year, month)[1])
    return source_date.replace(year=year, month=month, day=day)


def get_frequency_expiration_date(completed_date, frequency):
    if not completed_date:
        return None
    if frequency == 'annually':
        return add_months(completed_date, 12)
    if frequency == 'bi-annually':
        return add_months(completed_date, 6)
    return None

class Course(models.Model):
    name = models.CharField(max_length=255)
    link = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    date_created = models.DateTimeField(auto_now_add=True)
    upload = models.BooleanField(default=False)

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Course"
        verbose_name_plural = "Courses"


class Account(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ('system_admin', 'System Administrators'),
        ('cui_user', 'CUI Users'),
        ('non_cui_user', 'NON CUI Users'),
        ('sso', 'SSO'),
        ('iso', 'ISO'),
        ('info_owner', 'Information Owner (IO)'),
        ('external_temp', 'External/Temp Users'),
    ]
    type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.get_type_display()

class Matrix(models.Model):
    FREQUENCY_CHOICES = [
        ('once', 'Once'),
        ('annually', 'Annually'),
        ('bi-annually', 'Semi-Annual'),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    frequency = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        choices=FREQUENCY_CHOICES
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.account.get_type_display()} - {self.course}"
    
    class Meta:
        verbose_name = "Matrix"
        verbose_name_plural = "Matrices"

class UserAccount(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='account_links')
    account = models.ForeignKey('Account', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('user', 'account') # Ensure a user can't be linked to the same account twice

    def __str__(self):
        return f"{self.user.username} - {self.account.get_type_display()}"

class Tracker(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    matrix = models.ForeignKey(Matrix, on_delete=models.CASCADE)
    completed_date = models.DateField(default=timezone.now)
    document = models.BinaryField(blank=True, null=True)
    document_name = models.CharField(max_length=255, blank=True, null=True)

    @property
    def expiration_date(self):
        return get_frequency_expiration_date(self.completed_date, self.matrix.frequency)

    def __str__(self):
        return f"{self.user.username} - {self.matrix} (Completed: {self.completed_date})"

    class Meta:
        # Removed the unique_together constraint
        ordering = ['-completed_date'] # Order by most recent completion

class ArcticWolfCourse(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    course_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True) # New slug field

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super(ArcticWolfCourse, self).save(*args, **kwargs)

class ArcticWolfCompletion(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    course = models.ForeignKey(ArcticWolfCourse, on_delete=models.CASCADE)
    completed_date = models.DateField(blank=True, null=True)

    class Meta:
        unique_together = ('user', 'course') # Ensure a user can't have multiple completion records for the same course

    def __str__(self):
        return f"{self.user.username} - {self.course}"


class CourseReviewClick(models.Model):
    """
    Tracks when a user follows the course/policy review link from the requirements page.
    Stores first click and latest click for accountability.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    matrix = models.ForeignKey(Matrix, on_delete=models.CASCADE)
    first_clicked = models.DateTimeField()
    last_clicked = models.DateTimeField()

    class Meta:
        unique_together = ('user', 'matrix')

    def __str__(self):
        return f"{self.user.username} - {self.matrix.course.name} review clicks"
