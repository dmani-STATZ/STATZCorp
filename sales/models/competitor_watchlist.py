from django.conf import settings
from django.db import models


class CompetitorWatchlist(models.Model):
    """
    Shared, visible-to-everyone watchlist of competitor CAGE codes for the
    Competitors Numbers page. Anyone can add; only the user who added a
    given entry may remove it.
    """

    cage_code = models.CharField(max_length=10, unique=True, db_index=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="competitor_watchlist_entries",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sales_competitor_watchlist"
        ordering = ["-added_at"]

    def __str__(self):
        return self.cage_code
