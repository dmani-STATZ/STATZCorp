"""
Quotes app settings (services/app_settings.py owns the registry and every write).

Tables: quote_setting (current values), quote_setting_change (append-only audit),
quote_test_send (one row per RFQ Test Mode send attempt).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class QuoteSetting(models.Model):
    """One row per registry key that has ever been saved. A missing row means the registry default."""

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True, default='')
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        db_index=False,
    )
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'quote_setting'
        verbose_name = 'Quote setting'
        verbose_name_plural = 'Quote settings'

    def __str__(self):
        return self.key


class QuoteSettingChange(models.Model):
    """Who changed which setting, from what, to what. Never edited or deleted by code."""

    key = models.CharField(max_length=100, db_index=True)
    old_value = models.TextField(blank=True, default='')
    new_value = models.TextField(blank=True, default='')
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        db_index=False,
    )
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'quote_setting_change'
        ordering = ['-id']
        verbose_name = 'Quote setting change'
        verbose_name_plural = 'Quote setting changes'

    def __str__(self):
        return f'{self.key} changed {self.changed_at:%Y-%m-%d %H:%M}'


class QuoteTestSend(models.Model):
    """A supplier email that Test Mode sent to the test recipient instead (or refused to send)."""

    KIND_RFQ = 'rfq'
    KIND_PACKHOUSE = 'packhouse'
    KIND_CHOICES = [(KIND_RFQ, 'RFQ'), (KIND_PACKHOUSE, 'Packhouse')]

    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    ok = models.BooleanField(default=False)
    test_recipient = models.CharField(max_length=254, blank=True, default='')
    intended_to = models.TextField(blank=True, default='')
    intended_cc = models.TextField(blank=True, default='')
    intended_bcc = models.TextField(blank=True, default='')
    subject = models.CharField(max_length=255, blank=True, default='')
    sol_numbers = models.CharField(max_length=500, blank=True, default='')
    error_text = models.TextField(blank=True, default='')
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        db_index=False,
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'quote_test_send'
        ordering = ['-id']
        verbose_name = 'Quote test send'
        verbose_name_plural = 'Quote test sends'

    def __str__(self):
        return f'{self.kind} test send to {self.test_recipient} ({"ok" if self.ok else "failed"})'
