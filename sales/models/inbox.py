"""
Graph inbox persistence: linked supplier reply emails (RFQ Center).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class InboxMessage(models.Model):
    """
    Stores an email from the GRAPH_MAIL_SENDER mailbox that has been linked
    to one or more SupplierRFQ records by a sales rep. Unlinked emails are
    never persisted — they are fetched live from Graph.
    """

    class Meta:
        db_table = 'dibbs_inbox_message'
        ordering = ['-received_at']
        verbose_name = 'Inbox Message'
        verbose_name_plural = 'Inbox Messages'

    graph_message_id = models.CharField(
        max_length=512,
        unique=True,
        help_text='The immutable Graph message ID from the mailbox.',
    )
    sender_email = models.EmailField(
        max_length=255,
        help_text='Email address of the sender (supplier contact).',
    )
    sender_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Display name of the sender as provided by Graph.',
    )
    subject = models.CharField(
        max_length=998,
        blank=True,
        default='',
        help_text='Email subject line.',
    )
    received_at = models.DateTimeField(
        help_text='Timestamp the message was received, from Graph metadata.',
    )
    body_html = models.TextField(
        blank=True,
        default='',
        help_text=(
            'Raw HTML body from Graph. Rendered only inside a sandboxed iframe '
            'with no-scripts policy. Never injected directly into the page DOM.'
        ),
    )
    is_read = models.BooleanField(
        default=False,
        help_text='Read status at time of last fetch. Not synced continuously.',
    )
    linked_at = models.DateTimeField(
        default=timezone.now,
        help_text='When this message was first linked to an RFQ by a sales rep.',
    )

    def __str__(self):
        subj = (self.subject or '')[:60]
        return f'{self.sender_email} — {subj} ({self.received_at.strftime("%Y-%m-%d")})'


class InboxMessageRFQLink(models.Model):
    """
    Many-to-many bridge between InboxMessage and SupplierRFQ.
    One supplier reply email may cover multiple SOLs sent in a grouped RFQ.
    Each link represents one sales rep assignment of an email to one RFQ.
    """

    class Meta:
        db_table = 'dibbs_inbox_message_rfq_link'
        unique_together = [('message', 'rfq')]
        verbose_name = 'Inbox Message RFQ Link'
        verbose_name_plural = 'Inbox Message RFQ Links'

    message = models.ForeignKey(
        'sales.InboxMessage',
        on_delete=models.CASCADE,
        related_name='rfq_links',
    )
    rfq = models.ForeignKey(
        'sales.SupplierRFQ',
        on_delete=models.CASCADE,
        related_name='inbox_links',
    )
    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text='The sales rep who created this link.',
    )
    linked_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(
        blank=True,
        default='',
        help_text='Optional free-text note from the sales rep at link time.',
    )

    def __str__(self):
        return f'Msg {self.message_id} → RFQ {self.rfq_id}'
