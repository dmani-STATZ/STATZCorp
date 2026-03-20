from django.db import models


class RFQGreeting(models.Model):
    text = models.TextField(
        help_text="Greeting phrase. Use {supplier_name} or {contact_name} as variables."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dibbs_rfq_greeting"
        ordering = ["id"]

    def __str__(self):
        return self.text[:60]


class RFQSalutation(models.Model):
    text = models.TextField(
        help_text="Closing phrase. Use {your_name} or {your_email} as variables."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dibbs_rfq_salutation"
        ordering = ["id"]

    def __str__(self):
        return self.text[:60]
