from django.db import models

from .awards import DibbsAward


class CompetitorAwardEntity(models.Model):
    CODE_TYPE_CAGE = "CAGE"
    CODE_TYPE_DODAAC = "DODAAC"
    CODE_TYPE_UNKNOWN = "UNKNOWN"
    CODE_TYPE_CHOICES = [
        (CODE_TYPE_CAGE, "CAGE"),
        (CODE_TYPE_DODAAC, "DoDAAC"),
        (CODE_TYPE_UNKNOWN, "Unknown"),
    ]

    ROLE_CONTRACTOR = "CONTRACTOR"
    ROLE_OEM_DESIGN_AUTHORITY = "OEM_DESIGN_AUTHORITY"
    ROLE_MANUFACTURER = "MANUFACTURER"
    ROLE_BUYER = "BUYER"
    ROLE_PAYMENT_OFFICE = "PAYMENT_OFFICE"
    ROLE_PACKAGING = "PACKAGING"
    ROLE_OTHER = "OTHER"
    ROLE_CHOICES = [
        (ROLE_CONTRACTOR, "Contractor"),
        (ROLE_OEM_DESIGN_AUTHORITY, "OEM / Design Authority"),
        (ROLE_MANUFACTURER, "Manufacturer"),
        (ROLE_BUYER, "Buyer"),
        (ROLE_PAYMENT_OFFICE, "Payment Office"),
        (ROLE_PACKAGING, "Packaging"),
        (ROLE_OTHER, "Other"),
    ]

    METHOD_REGEX = "REGEX"
    METHOD_LLM = "LLM"
    METHOD_CHOICES = [
        (METHOD_REGEX, "Regex"),
        (METHOD_LLM, "LLM"),
    ]

    # Roles excluded from "who does this competitor source from" rankings.
    RANKING_EXCLUDED_ROLES = frozenset({ROLE_BUYER, ROLE_PAYMENT_OFFICE})

    award = models.ForeignKey(
        DibbsAward,
        on_delete=models.CASCADE,
        related_name="entities",
    )
    code = models.CharField(max_length=10, db_index=True)
    code_type = models.CharField(
        max_length=10, choices=CODE_TYPE_CHOICES, default=CODE_TYPE_UNKNOWN
    )
    role = models.CharField(
        max_length=30, choices=ROLE_CHOICES, default=ROLE_OTHER, db_index=True
    )
    entity_name = models.CharField(max_length=255, blank=True, default="")
    source_note = models.TextField(blank=True, default="")
    extraction_method = models.CharField(
        max_length=10, choices=METHOD_CHOICES, default=METHOD_REGEX
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sales_competitor_award_entity"
        ordering = ["role", "code"]

    def __str__(self):
        return f"{self.code} ({self.role}) on {self.award.notice_id}"
