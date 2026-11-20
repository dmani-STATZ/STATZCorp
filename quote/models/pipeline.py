"""
Automatic email pipeline (services/email_pipeline.py): the sender blocklist and one triage row per
supplier email received while Email scanning is on. Extraction rows live in ``QuoteEmailScan``.

Tables: quote_sender_block, quote_email_triage.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class QuoteSenderBlock(models.Model):
    """A sender we never send to Jev or Claude (services/blocklist.py owns every write)."""

    TYPE_CAGE = 'cage'
    TYPE_EMAIL = 'email'
    TYPE_DOMAIN = 'domain'
    TYPE_SUPPLIER = 'supplier'
    TYPE_CHOICES = [
        (TYPE_CAGE, 'CAGE'),
        (TYPE_EMAIL, 'Email address'),
        (TYPE_DOMAIN, 'Domain'),
        (TYPE_SUPPLIER, 'Supplier'),
    ]

    block_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    value = models.CharField(
        max_length=254,
        help_text='Normalized: CAGE upper-case, email / domain lower-case, supplier = the supplier id.',
    )
    label = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Company name. Only labeled entries are offered to Jev as possible blocked companies.',
    )
    reason = models.TextField(blank=True, default='')
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        db_index=False,
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        db_index=False,
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'quote_sender_block'
        ordering = ['-id']
        verbose_name = 'Quote sender block'
        verbose_name_plural = 'Quote sender blocks'
        constraints = [
            models.UniqueConstraint(fields=['block_type', 'value'], name='quote_sender_block_type_value'),
        ]

    def __str__(self):
        return f'{self.block_type}:{self.value}'


class QuoteEmailTriage(models.Model):
    """Where one email is in the automatic pipeline. See CONTEXT_quote.md §6 Phase 2 "Email pipeline"."""

    STATE_PENDING = 'pending'
    STATE_CLASSIFYING = 'classifying'
    STATE_BLOCKED = 'blocked'
    STATE_NOT_QUOTE = 'not_quote'
    STATE_HELD_UNKNOWN_SENDER = 'held_unknown_sender'
    STATE_HELD_POSSIBLE_BLOCK = 'held_possible_block'
    STATE_EXTRACT_QUEUED = 'extract_queued'
    STATE_EXTRACTED = 'extracted'
    STATE_FAILED = 'failed'
    STATE_CHOICES = [
        (STATE_PENDING, 'Pending'),
        (STATE_CLASSIFYING, 'Classifying'),
        (STATE_BLOCKED, 'Blocked'),
        (STATE_NOT_QUOTE, 'Not a quote'),
        (STATE_HELD_UNKNOWN_SENDER, 'Held: unknown sender'),
        (STATE_HELD_POSSIBLE_BLOCK, 'Held: possible blocked company'),
        (STATE_EXTRACT_QUEUED, 'Extraction queued'),
        (STATE_EXTRACTED, 'Extracted'),
        (STATE_FAILED, 'Failed'),
    ]

    email = models.OneToOneField('quote.QuoteEmail', on_delete=models.CASCADE, related_name='triage')
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=STATE_PENDING)
    reason = models.CharField(max_length=60, blank=True, default='')
    jev_quote_probability = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    jev_block_probability = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    threshold_used = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    jev_block_label = models.CharField(max_length=200, blank=True, default='')
    block_entry = models.ForeignKey(
        QuoteSenderBlock,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        db_index=False,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    error_text = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)
    classified_at = models.DateTimeField(null=True, blank=True)
    state_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'quote_email_triage'
        ordering = ['-id']
        verbose_name = 'Quote email triage'
        verbose_name_plural = 'Quote email triage'

    def __str__(self):
        return f'Email {self.email_id} {self.state}'
