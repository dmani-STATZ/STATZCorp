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
