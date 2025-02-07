from django.db import models
from django.utils import timezone

class Visitor(models.Model):
    date_of_visit = models.DateField(default=timezone.now)
    visitor_name = models.CharField(max_length=100)
    visitor_company = models.CharField(max_length=100)
    reason_for_visit = models.CharField(max_length=200)
    id_confirm = models.CharField(max_length=50, blank=True)
    time_in = models.TimeField()
    time_out = models.TimeField(null=True, blank=True)
    departed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date_of_visit', '-time_in']

    def __str__(self):
        return f"{self.visitor_name} - {self.date_of_visit}"
