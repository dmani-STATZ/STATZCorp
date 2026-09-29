"""
QuotePackhouseRFQ -- a packaging-quote request emailed to one packhouse.

Separate from QuoteRFQ on purpose: QuoteRFQ is the part-supplier ledger (one row
per line + supplier, and it drives the solicitation's RFQ_SENT status). A packhouse
request asks a different question (what would it cost to pack this?), carries the
part's weight / dimensions instead, and must never move the solicitation.

One row per packhouse per request. ``line`` is null when the request covers every
line on the solicitation (the drawer's Combined mode). The row keeps a snapshot of
what was sent so the request can be reproduced, and, later, what the packhouse
quoted so the rep can drop it into a supplier quote's packaging section.

Table: quote_packhouse_rfq.
"""
from django.conf import settings
from django.db import models

from .base import AuditModel


class QuotePackhouseRFQ(AuditModel):
    STATUS_SENT = 'SENT'
    STATUS_RESPONDED = 'RESPONDED'
    STATUS_CHOICES = [
        (STATUS_SENT, 'Sent'),
        (STATUS_RESPONDED, 'Replied'),
    ]

    # Read-only references into the dibbs / suppliers tables.
    solicitation = models.ForeignKey(
        'dibbs.Solicitation',
        on_delete=models.CASCADE,
        related_name='quote_packhouse_rfqs',
    )
    line = models.ForeignKey(
        'dibbs.SolicitationLine',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='quote_packhouse_rfqs',
        help_text='Null = the request covers every line on the solicitation.',
    )
    packhouse = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='quote_packhouse_rfqs',
    )

    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_SENT, db_index=True,
    )

    # ── What we sent (snapshot) ───────────────────────────────────────────
    quantity = models.PositiveIntegerField(
        help_text='Units the packhouse was asked to price (sum of the lines covered).',
    )
    unit_of_issue = models.CharField(max_length=10, blank=True, default='')
    weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True,
                                 help_text='Unit weight, lb, as sent.')
    length = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    width = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    subject = models.CharField(max_length=255, blank=True, default='')
    note = models.TextField(blank=True, default='',
                            help_text='The rep\'s own note to the packhouse.')
    email_sent_to = models.CharField(max_length=255, blank=True, default='')
    sent_at = models.DateTimeField()
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_packhouse_rfqs_sent',
    )

    # ── What they answered ────────────────────────────────────────────────
    response_email = models.ForeignKey(
        'quote.QuoteEmail',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='packhouse_replies',
        help_text='The mailbox message this request was answered by.',
    )
    response_received_at = models.DateTimeField(null=True, blank=True)
    quoted_total = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True,
        help_text='Total pack cost for ``quantity``, if the packhouse quoted a total.',
    )
    quoted_unit = models.DecimalField(
        max_digits=13, decimal_places=5, null=True, blank=True,
        help_text='Per-unit pack cost. Derived from the total when only that was quoted.',
    )
    quoted_lead_days = models.PositiveIntegerField(null=True, blank=True)
    response_notes = models.TextField(blank=True, default='')
    quoted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_packhouse_rfqs_recorded',
    )

    class Meta:
        db_table = 'quote_packhouse_rfq'
        verbose_name = 'Quote packhouse RFQ'
        verbose_name_plural = 'Quote packhouse RFQs'
        ordering = ['-sent_at', '-pk']
        indexes = [
            models.Index(fields=['solicitation', 'packhouse'], name='quote_phrfq_sol_ph'),
        ]

    def __str__(self):
        return f'Packhouse RFQ sol={self.solicitation_id} packhouse={self.packhouse_id} ({self.status})'

    @property
    def has_price(self) -> bool:
        return self.quoted_unit is not None
