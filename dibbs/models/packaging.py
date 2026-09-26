from django.db import models


class SolPackaging(models.Model):
    """
    Packaging requirements extracted from DIBBS solicitation PDF (Section D).
    Populated nightly by CA zip parse pipeline. One record per solicitation.
    """
    solicitation_number = models.CharField(max_length=50, unique=True, db_index=True)
    packaging_standard  = models.CharField(max_length=200, blank=True)
    preservation_requirements = models.TextField(blank=True)
    marking_requirements = models.TextField(blank=True)
    raw_section_d       = models.TextField(blank=True, help_text='Raw extracted Section D text for reference')
    extracted_at        = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dibbs_sol_packaging'

    def __str__(self):
        return f'Packaging — {self.solicitation_number}'
