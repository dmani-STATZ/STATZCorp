from django.db import models
from django.utils import timezone


class SAMEntityCache(models.Model):
    """
    Cached result of a SAM.gov CAGE lookup.
    Keyed on cage_code. Records older than 30 days are considered stale
    and will be refreshed on the next lookup.
    """

    SAM_CACHE_TTL_DAYS = 30

    cage_code = models.CharField(max_length=10, primary_key=True)

    # Core identity fields
    entity_name = models.CharField(max_length=255, blank=True, default="")
    website = models.CharField(max_length=500, blank=True, default="")

    # Physical address
    physical_address_line1 = models.CharField(max_length=255, blank=True, default="")
    physical_address_line2 = models.CharField(max_length=255, blank=True, default="")
    physical_city = models.CharField(max_length=100, blank=True, default="")
    physical_state = models.CharField(max_length=50, blank=True, default="")
    physical_zip = models.CharField(max_length=20, blank=True, default="")

    # Mailing address (raw string — SAM returns this less consistently)
    mailing_address = models.TextField(blank=True, default="")

    # Set-aside / SBA flags — stored as JSON array of code strings
    sba_flags = models.JSONField(default=list, blank=True)

    # NAICS and PSC codes — stored as JSON arrays
    naics_codes = models.JSONField(default=list, blank=True)
    psc_codes = models.JSONField(default=list, blank=True)

    # Full raw JSON response from SAM API — preserved for future use
    # (e.g. promoting a SAM record to a full Supplier)
    raw_json = models.JSONField(default=dict, blank=True)

    # Cache metadata
    last_fetched = models.DateTimeField()
    fetch_error = models.BooleanField(default=False)

    class Meta:
        app_label = "sales"
        db_table = "dibbs_sam_entity_cache"
        verbose_name = "SAM Entity Cache"

    def is_stale(self):
        """Returns True if the cache record is older than SAM_CACHE_TTL_DAYS."""
        age = timezone.now() - self.last_fetched
        return age.days >= self.SAM_CACHE_TTL_DAYS

    @property
    def days_since_fetch(self):
        """How many days ago this record was last fetched from SAM."""
        return (timezone.now() - self.last_fetched).days

    def __str__(self):
        return f"{self.cage_code} — {self.entity_name or '(no name)'}"
