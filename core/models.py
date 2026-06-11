from django.db import models

class APIBudget(models.Model):
    balance_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    last_sync_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "API Budget"

    def save(self, *args, **kwargs):
        # Enforce singleton  always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

class APIUsageLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    call_site = models.CharField(max_length=100)  # e.g. "intake.pdf_parser.extract_clins"
    model = models.CharField(max_length=100)
    input_tokens = models.IntegerField()
    output_tokens = models.IntegerField()
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6)

    class Meta:
        ordering = ['-timestamp']


class ScheduledTask(models.Model):
    """
    Registry of background tasks with per-task scheduling metadata.
    The run_background_tasks management command reads this table on every
    WebJob heartbeat to determine which tasks are due to run.
    """
    name = models.CharField(max_length=100, unique=True)
    interval_minutes = models.IntegerField()
    run_order = models.IntegerField(default=0, help_text="Lower numbers run first when multiple tasks are due simultaneously.")
    last_run_at = models.DateTimeField(null=True, blank=True)
    is_running = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)
    freeze_count = models.IntegerField(default=0, help_text="Incremented each time a stale lock is detected and cleared on this task.")

    class Meta:
        ordering = ['run_order']

    def __str__(self):
        return self.name
