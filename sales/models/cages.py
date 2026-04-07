"""
CompanyCAGE — company-level CAGE settings for BQ export. Section 8.1.
Table: dibbs_company_cage.
"""
from django.db import models


class CompanyCAGE(models.Model):
    """One row per registered CAGE code (company may bid under multiple CAGEs)."""
    cage_code = models.CharField(max_length=5, unique=True)
    company_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Legacy display label; prefer linking contracts.Company via 'company'.",
    )
    company = models.ForeignKey(
        "contracts.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cage_codes",
        verbose_name="Linked Company",
        help_text=(
            "Link this CAGE code to the corresponding company in the contracts system. "
            "Required for automatic award queue injection."
        ),
    )
    sb_representations_code = models.CharField(max_length=1)  # A/B/C/E/F/G/M/P/X
    affirmative_action_code = models.CharField(max_length=2)  # Y6/N6/NH/NA
    previous_contracts_code = models.CharField(max_length=2)  # Y4/Y5/N4/NA
    alternate_disputes_resolution = models.CharField(max_length=1)  # A or B
    default_fob_point = models.CharField(max_length=1, default='D')
    default_payment_terms = models.CharField(max_length=2, default='1')
    default_child_labor_code = models.CharField(max_length=1, default='N')
    default_markup_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=3.50,
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    smtp_reply_to = models.EmailField(null=True, blank=True)

    class Meta:
        db_table = 'dibbs_company_cage'
        verbose_name = 'Company CAGE'
        verbose_name_plural = 'Company CAGEs'
