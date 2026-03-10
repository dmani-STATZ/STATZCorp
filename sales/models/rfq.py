"""
SupplierRFQ, SupplierContactLog — Section 3.4 and 10.6.
Tables: dibbs_supplier_rfq, dibbs_supplier_contact_log.
"""
from django.conf import settings
from django.db import models


class SupplierRFQ(models.Model):
    """RFQ sent to a supplier for a solicitation line."""
    STATUS_CHOICES = [
        ('SENT', 'Sent'),
        ('RESPONDED', 'Responded'),
        ('NO_RESPONSE', 'No Response'),
        ('DECLINED', 'Declined'),
    ]
    line = models.ForeignKey(
        'SolicitationLine',
        on_delete=models.CASCADE,
        related_name='rfqs',
    )
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='dibbs_rfqs',
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_rfqs_sent',
    )
    email_sent_to = models.EmailField()
    response_received_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SENT')

    class Meta:
        db_table = 'dibbs_supplier_rfq'
        verbose_name = 'Supplier RFQ'
        verbose_name_plural = 'Supplier RFQs'


class SupplierContactLog(models.Model):
    """Track all supplier touchpoints (email, phone, notes)."""
    CONTACT_METHOD = [
        ('EMAIL_OUT', 'Outbound Email'),
        ('EMAIL_IN', 'Inbound Email'),
        ('PHONE', 'Phone Call'),
        ('FOLLOWUP', 'Follow-up Email'),
        ('NOTE', 'Internal Note'),
    ]
    DIRECTION_CHOICES = [
        ('IN', 'Inbound'),
        ('OUT', 'Outbound'),
    ]
    rfq = models.ForeignKey(
        SupplierRFQ,
        on_delete=models.CASCADE,
        related_name='contact_log',
        null=True,
        blank=True,
    )
    supplier = models.ForeignKey(
        'suppliers.Supplier',
        on_delete=models.CASCADE,
        related_name='contact_log',
    )
    solicitation = models.ForeignKey(
        'Solicitation',
        on_delete=models.CASCADE,
        related_name='contact_log',
        null=True,
        blank=True,
    )
    method = models.CharField(max_length=20, choices=CONTACT_METHOD)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    summary = models.TextField()
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_contact_logs',
    )
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dibbs_supplier_contact_log'
        ordering = ['-logged_at']
        verbose_name = 'Supplier contact log'
        verbose_name_plural = 'Supplier contact logs'
