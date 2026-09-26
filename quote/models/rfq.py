"""
QuoteRFQ — outbound RFQ dispatch record, one row per (solicitation line, supplier).

The quote app's outbound RFQ dispatch ledger. Table: quote_rfq.
"""
from django.conf import settings
from django.db import models

from .base import AuditModel


class QuoteRFQ(AuditModel):
    """One RFQ sent (or queued) to one supplier for one solicitation line."""

    STATUS_QUEUED = 'QUEUED'
    STATUS_READY_TO_SEND = 'READY_TO_SEND'
    STATUS_SENT = 'SENT'
    STATUS_RESPONDED = 'RESPONDED'
    STATUS_NO_RESPONSE = 'NO_RESPONSE'
    STATUS_DECLINED = 'DECLINED'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_READY_TO_SEND, 'Ready to send'),
        (STATUS_SENT, 'Sent'),
        (STATUS_RESPONDED, 'Responded'),
        (STATUS_NO_RESPONSE, 'No response'),
        (STATUS_DECLINED, 'Declined'),
    ]

    # Read-only reference into the dibbs tables.
    line = models.ForeignKey(
        'dibbs.SolicitationLine',
        on_delete=models.CASCADE,
        related_name='quote_rfqs',
    )
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='quote_rfqs',
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_QUEUED,
        db_index=True,
    )
    personalization_text = models.TextField(
        blank=True,
        default='',
        help_text='Free text injected into this supplier\'s outbound RFQ email.',
    )
    email_sent_to = models.CharField(max_length=255, blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_rfqs_sent',
    )
    response_received_at = models.DateTimeField(null=True, blank=True)
    follow_up_sent_at = models.DateTimeField(null=True, blank=True)
    follow_up_count = models.PositiveSmallIntegerField(default=0)

    # Async Graph dispatch diagnostics.
    send_attempts = models.PositiveSmallIntegerField(default=0)
    last_send_error = models.TextField(blank=True, default='')

    declined_reason = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'quote_rfq'
        unique_together = [('line', 'supplier')]
        verbose_name = 'Quote RFQ'
        verbose_name_plural = 'Quote RFQs'
        indexes = [
            models.Index(fields=['status', 'sent_at'], name='quote_rfq_status_sent'),
        ]

    def __str__(self):
        return f'RFQ line={self.line_id} supplier={self.supplier_id} ({self.status})'
