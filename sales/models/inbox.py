"""
InboxEmail — stores emails fetched via IMAP for the RFQ inbox tab.
"""
from django.db import models


class InboxEmail(models.Model):
    message_id = models.CharField(max_length=500, unique=True)
    from_email = models.EmailField()
    from_name = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=500, blank=True)
    body_text = models.TextField(blank=True)
    received_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    rfq = models.ForeignKey(
        'sales.SupplierRFQ',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='inbox_emails',
    )
    is_read = models.BooleanField(default=False)
    is_matched = models.BooleanField(default=False)

    class Meta:
        db_table = 'sales_inbox_email'
        ordering = ['-received_at']
        verbose_name = 'Inbox Email'
        verbose_name_plural = 'Inbox Emails'

    def __str__(self):
        return f"{self.from_name or self.from_email}: {self.subject[:60]}"
