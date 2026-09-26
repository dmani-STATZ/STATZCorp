"""
QuoteSolicitation -- the quoting workflow state of one DIBBS solicitation.

The dibbs app stores what DIBBS published and nothing else. Everything the
quoting team does to a solicitation (its place in the pipeline, who is
reviewing it) lives here, one row per solicitation.

Table: quote_solicitation.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .base import AuditModel
from .email import CLAIM_DURATION


class QuoteSolicitation(AuditModel):
    """Pipeline state + review claim for one solicitation."""

    STATUS_UNMATCHED = 'UNMATCHED'
    STATUS_MATCHED = 'MATCHED'
    STATUS_RFQ_SENT = 'RFQ_SENT'
    STATUS_QUOTING = 'QUOTING'
    STATUS_BID_READY = 'BID_READY'
    STATUS_BID_SUBMITTED = 'BID_SUBMITTED'
    STATUS_NO_BID = 'NO_BID'
    STATUS_ARCHIVED = 'ARCHIVED'
    STATUS_CHOICES = [
        (STATUS_UNMATCHED, 'Unmatched'),
        (STATUS_MATCHED, 'Matched'),
        (STATUS_RFQ_SENT, 'RFQ sent'),
        (STATUS_QUOTING, 'Quoting'),
        (STATUS_BID_READY, 'Bid ready'),
        (STATUS_BID_SUBMITTED, 'Bid submitted'),
        (STATUS_NO_BID, 'No bid'),
        (STATUS_ARCHIVED, 'Archived'),
    ]

    #: Seeded automatically for every imported solicitation, so a row here is
    #: not "work" -- dibbs' import-batch delete may cascade through it.
    dibbs_disposable = True

    #: States the matching engine may move between. Once a rep has dispatched
    #: an RFQ (or passed / bid), re-running matching never rewinds the status.
    MATCHING_STATES = frozenset({STATUS_UNMATCHED, STATUS_MATCHED})

    # Read-only reference into the dibbs tables.
    solicitation = models.OneToOneField(
        'dibbs.Solicitation',
        on_delete=models.CASCADE,
        related_name='quote_state',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_UNMATCHED,
        db_index=True,
    )
    status_changed_at = models.DateTimeField(default=timezone.now)

    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_claimed_solicitations',
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_expires_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'quote_solicitation'
        verbose_name = 'Quote solicitation'
        verbose_name_plural = 'Quote solicitations'
        indexes = [
            models.Index(fields=['status', 'status_changed_at'],
                         name='quote_sol_status_changed'),
        ]

    def __str__(self):
        return f'{self.solicitation_id} ({self.status})'

    def set_status(self, status):
        """Change status and stamp status_changed_at. Caller saves."""
        if status != self.status:
            self.status = status
            self.status_changed_at = timezone.now()

    def is_claimed_by_other(self, user) -> bool:
        """True when another user holds an active, unexpired claim."""
        if not self.claimed_by_id or not self.claim_expires_at:
            return False
        if self.claimed_by_id == user.pk:
            return False
        return self.claim_expires_at >= timezone.now()

    def claim_for(self, user):
        """Take the claim, releasing any other solicitation this user held."""
        QuoteSolicitation.objects.filter(claimed_by=user).exclude(pk=self.pk).update(
            claimed_by=None, claimed_at=None, claim_expires_at=None,
        )
        now = timezone.now()
        self.claimed_by = user
        self.claimed_at = now
        self.claim_expires_at = now + CLAIM_DURATION
        self.save(update_fields=['claimed_by', 'claimed_at', 'claim_expires_at'])
