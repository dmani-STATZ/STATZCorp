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
    claimed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='claimed_inbox_messages',
        help_text='The user who currently has this message open and is working it.',
    )
    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the current claim was made. Claims expire after 20 minutes.',
    )
    claim_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Precomputed expiry timestamp (claimed_at + 20 minutes). Null means no active claim.',
    )

    def __str__(self):
        subj = (self.subject or '')[:60]
        return f'{self.sender_email} — {subj} ({self.received_at.strftime("%Y-%m-%d")})'

    def is_claimed_by_other(self, user):
        """
        Returns True if this message has an active, non-expired claim by someone
        other than `user`. Returns False if:
        - No claim exists
        - Claim has expired (claim_expires_at < now)
        - The claim belongs to `user` themselves
        - The message is already linked (has rfq_links)
        """
        from django.utils import timezone
        if not self.claimed_by_id or not self.claim_expires_at:
            return False
        if self.claimed_by_id == user.pk:
            return False
        if self.claim_expires_at < timezone.now():
            return False
        return True

    def claim_for(self, user):
        from django.utils import timezone
        from datetime import timedelta

        # Release any other messages this user currently has claimed
        InboxMessage.objects.filter(
            claimed_by=user
        ).exclude(
            pk=self.pk
        ).update(
            claimed_by=None,
            claimed_at=None,
            claim_expires_at=None
        )

        # Now claim this message
        now = timezone.now()
        self.claimed_by = user
        self.claimed_at = now
        self.claim_expires_at = now + timedelta(minutes=20)
        self.save(update_fields=['claimed_by', 'claimed_at', 'claim_expires_at'])


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
