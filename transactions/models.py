"""
Store field-level change history for auditable models.
Only changes are recorded (not initial creation).
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

User = get_user_model()


class Transaction(models.Model):
    """
    One row per field change: table + record id + field + old/new + user + datetime.
    Enables itemizable history (all transactions for a record, or for a field).
    """
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        help_text="Model (table) that was changed",
    )
    object_id = models.PositiveIntegerField(
        help_text="Primary key of the record that was changed",
    )
    content_object = GenericForeignKey("content_type", "object_id")

    field_name = models.CharField(max_length=64, db_index=True)
    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="field_transactions",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"], name="tx_content_object_idx"),
            models.Index(fields=["content_type", "object_id", "field_name"], name="tx_field_history_idx"),
        ]
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"

    def __str__(self):
        return f"{self.content_type.model}#{self.object_id}.{self.field_name} @ {self.created_at}"

    @property
    def table_name(self):
        return self.content_type.model if self.content_type_id else ""
