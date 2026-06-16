from django.db import models


class DibbsNotice(models.Model):
    """
    A public notice scraped from the DIBBS homepage (www.dibbs.bsm.dla.mil).
    Examples: CMMC compliance updates, PAR code changes, cybersecurity posture
    announcements posted by DLA. Keyed on (title, posted_date) — never updated
    after creation; get_or_create only.
    """

    title = models.CharField(max_length=500)
    external_url = models.URLField(max_length=1000)
    posted_date = models.DateField()
    discovered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("title", "posted_date")]
        ordering = ["-posted_date"]
        verbose_name = "DIBBS Notice"
        verbose_name_plural = "DIBBS Notices"

    def __str__(self):
        return f"{self.posted_date} — {self.title[:80]}"
