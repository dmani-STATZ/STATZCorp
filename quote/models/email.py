"""
Inbound supplier email persistence for the quotes@ shared mailbox.

Every message in the mailbox is persisted -- linked or not -- with its raw
Graph payload, headers and attachments, because the mailbox workspace needs all
three.

Tables: quote_email, quote_email_attachment, quote_email_sol_link.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .base import AuditModel

#: How long a rep holds an email before another rep can take it. Matches the
#: 20-minute convention used by every claim in this app (see
#: QuoteSolicitation.claim_for). Changing this means updating CONTEXT_quote.md
#: and AGENTS_quote.md too.
CLAIM_DURATION = timedelta(minutes=20)


class QuoteEmail(AuditModel):
    """One message from the quotes@ mailbox, with its raw Graph payload kept."""

    graph_message_id = models.CharField(
        max_length=512,
        unique=True,
        help_text='Immutable Graph message ID.',
    )
    sender_email = models.EmailField(max_length=255)
    sender_name = models.CharField(max_length=255, blank=True, default='')
    subject = models.CharField(max_length=998, blank=True, default='')
    received_at = models.DateTimeField(db_index=True)
    body_preview = models.TextField(blank=True, default='')
    body_html = models.TextField(
        blank=True,
        default='',
        help_text='Raw HTML body. Rendered ONLY inside a sandboxed no-scripts '
                  'iframe -- never injected into the page DOM.',
    )
    headers_json = models.JSONField(
        null=True,
        blank=True,
        help_text='Internet message headers as returned by Graph.',
    )
    raw_payload = models.JSONField(
        null=True,
        blank=True,
        help_text='Full Graph message resource, preserved verbatim.',
    )
    is_read = models.BooleanField(default=False)

    #: Supplier resolved from the sender address (contact email, supplier
    #: emails, then domain). Null when unknown -- the rep picks one when logging.
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_emails',
    )

    #: True when no solicitation could be detected from subject or body -- the
    #: "No SOL in Subject" orphan pill in the mailbox list.
    is_orphan = models.BooleanField(default=True, db_index=True)

    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_claimed_emails',
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'quote_email'
        ordering = ['-received_at']
        verbose_name = 'Quote email'
        verbose_name_plural = 'Quote emails'

    def __str__(self):
        return f'{self.sender_email} — {(self.subject or "")[:60]}'

    def is_claimed_by_other(self, user) -> bool:
        """True when another user holds an active, unexpired claim."""
        if not self.claimed_by_id or not self.claim_expires_at:
            return False
        if self.claimed_by_id == user.pk:
            return False
        return self.claim_expires_at >= timezone.now()

    def try_claim(self, user) -> bool:
        """Atomically take or renew the claim (see QuoteSolicitation.try_claim)."""
        now = timezone.now()
        won = QuoteEmail.objects.filter(pk=self.pk).filter(
            Q(claimed_by__isnull=True) | Q(claim_expires_at__lt=now) | Q(claimed_by=user)
        ).update(claimed_by=user, claimed_at=now, claim_expires_at=now + CLAIM_DURATION)
        if won:
            QuoteEmail.objects.filter(claimed_by=user).exclude(pk=self.pk).update(
                claimed_by=None, claimed_at=None, claim_expires_at=None,
            )
        self.refresh_from_db(fields=['claimed_by', 'claimed_at', 'claim_expires_at'])
        return bool(won)

    def claim_for(self, user):
        """Take the claim, releasing any other email this user was holding."""
        QuoteEmail.objects.filter(claimed_by=user).exclude(pk=self.pk).update(
            claimed_by=None, claimed_at=None, claim_expires_at=None,
        )
        now = timezone.now()
        self.claimed_by = user
        self.claimed_at = now
        self.claim_expires_at = now + CLAIM_DURATION
        self.save(update_fields=['claimed_by', 'claimed_at', 'claim_expires_at'])


class QuoteEmailAttachment(models.Model):
    """A file that arrived on a QuoteEmail. Bytes are stored, not just referenced."""

    email = models.ForeignKey(
        QuoteEmail,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    graph_attachment_id = models.CharField(max_length=512, blank=True, default='')
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=127, blank=True, default='')
    file_size = models.PositiveIntegerField(default=0)
    content = models.BinaryField(
        null=True,
        blank=True,
        help_text='Attachment bytes. Nullable so metadata can land before the '
                  'download completes.',
    )
    downloaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'quote_email_attachment'
        unique_together = [('email', 'graph_attachment_id')]
        verbose_name = 'Quote email attachment'
        verbose_name_plural = 'Quote email attachments'

    def __str__(self):
        return f'{self.original_name} ({self.file_size} bytes)'

    #: File extensions the split-screen viewer offers a preview for. Only a hint for the
    #: button: ``mailbox.sniff_preview_type`` decides from the bytes when it is served.
    PREVIEW_EXTENSIONS = {
        '.pdf': 'pdf',
        '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.gif': 'image', '.webp': 'image',
    }

    @property
    def preview_kind(self) -> str:
        """'pdf' / 'image' when the viewer can show this file, else ''."""
        if not self.downloaded_at:
            return ''
        ext = '.' + self.original_name.rsplit('.', 1)[-1].lower() if '.' in self.original_name else ''
        return self.PREVIEW_EXTENSIONS.get(ext, '')


class QuoteEmailSolLink(models.Model):
    """
    Quote.md's SOL_Email_Link. Many-to-many between an email and the
    solicitation lines it covers -- one supplier reply to a consolidated RFQ can
    price several lines, and one line accumulates several emails over time.
    """

    email = models.ForeignKey(
        QuoteEmail,
        on_delete=models.CASCADE,
        related_name='sol_links',
    )
    # Read-only reference into the dibbs tables.
    line = models.ForeignKey(
        'dibbs.SolicitationLine',
        on_delete=models.CASCADE,
        related_name='quote_email_links',
    )
    detected_automatically = models.BooleanField(
        default=False,
        help_text='True when the sol number was found in the subject or body; '
                  'False when a rep linked it by hand.',
    )
    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    linked_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'quote_email_sol_link'
        unique_together = [('email', 'line')]
        verbose_name = 'Quote email solicitation link'
        verbose_name_plural = 'Quote email solicitation links'

    def __str__(self):
        return f'Email {self.email_id} → line {self.line_id}'
