"""
CompanyCAGE — company-level CAGE settings for BQ export. Section 8.1.
Table: dibbs_company_cage.
"""
from django.db import models


class CompanyCAGE(models.Model):
    """One row per registered CAGE code (company may bid under multiple CAGEs)."""
    cage_code = models.CharField(max_length=5, unique=True)
    company_name = models.CharField(max_length=150)
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

    # IMAP inbox settings
    # IMAP inbox — delegated OAuth2 only (no basic auth in GCC High Exchange Online)
    # imap_user is the shared mailbox address (e.g. sales@statzcorp.com),
    # NOT the employee's address. The signed-in employee's delegated token is
    # used to authenticate; their exchange rights to the shared mailbox grant access.
    imap_host = models.CharField(max_length=255, null=True, blank=True)
    imap_port = models.IntegerField(default=993)
    imap_user = models.CharField(
        max_length=255, null=True, blank=True,
        help_text='Shared mailbox address, e.g. sales@statzcorp.com'
    )
    imap_folder = models.CharField(max_length=100, default='INBOX')
    imap_last_fetched = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'dibbs_company_cage'
        verbose_name = 'Company CAGE'
        verbose_name_plural = 'Company CAGEs'
