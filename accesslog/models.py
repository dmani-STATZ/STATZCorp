from django.db import models
from django.utils import timezone
from datetime import datetime

class Visitor(models.Model):
    date_of_visit = models.DateField(default=timezone.now)
    visitor_name = models.CharField(max_length=100)
    visitor_company = models.CharField(max_length=100)
    reason_for_visit = models.CharField(max_length=200)
    is_us_citizen = models.BooleanField(default=False)
    time_in = models.DateTimeField(default=timezone.now)
    time_out = models.DateTimeField(null=True, blank=True)
    departed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date_of_visit', '-time_in']

    def __str__(self):
        return f"{self.visitor_name} - {self.date_of_visit}"


class Staged(models.Model):
    visitor_name = models.CharField(max_length=100)
    visitor_company = models.CharField(max_length=100)
    reason_for_visit = models.CharField(max_length=200)
    is_us_citizen = models.BooleanField(default=False)
    date_added = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.visitor_name} - {self.visitor_company}"
