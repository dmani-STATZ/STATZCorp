from django.conf import settings
from django.db import models


class NoQuoteCAGE(models.Model):
    """
    Tracks CAGE codes that have declined to work with us.
    Uses soft-delete: set is_active=False + deactivated_at when a supplier relationship is restored.
    A CAGE is considered on the No Quote list only when is_active=True.
    """

    cage_code = models.CharField(
        max_length=5,
        db_index=True,
        help_text="Five-character CAGE code.",
    )
    reason = models.TextField(
        blank=True,
        help_text="Optional reason or notes recorded by the team member.",
    )
    date_added = models.DateField(auto_now_add=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="no_quote_cages_added",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="True = currently on the No Quote list. False = previously flagged but restored.",
    )
    deactivated_at = models.DateField(
        null=True,
        blank=True,
        help_text="Date the record was marked inactive (supplier restored).",
    )

    class Meta:
        db_table = "dibbs_no_quote_cage"
        ordering = ["-date_added"]
        constraints = [
            models.UniqueConstraint(
                fields=["cage_code"],
                condition=models.Q(is_active=True),
                name="unique_active_no_quote_cage",
            )
        ]

    def __str__(self):
        return f"NoQuote: {self.cage_code} ({'active' if self.is_active else 'inactive'})"
