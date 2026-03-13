"""
EmailTemplate — configurable RFQ email subject/body with variable substitution.
Table: dibbs_email_template.
"""
from django.db import models
from django.contrib.auth.models import User


class _SafeDict(dict):
    """Returns empty string for missing keys so partial templates don't crash."""

    def __missing__(self, key):
        return ""


class EmailTemplate(models.Model):
    name = models.CharField(max_length=100)
    subject_template = models.CharField(max_length=255)
    body_template = models.TextField()
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_templates_created",
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dibbs_email_template"
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name

    def render_subject(self, context: dict) -> str:
        """Render subject with variable substitution. Missing keys render as empty string."""
        try:
            return self.subject_template.format_map(_SafeDict(context))
        except Exception:
            return self.subject_template

    def render_body(self, context: dict) -> str:
        """Render body with variable substitution. Missing keys render as empty string."""
        try:
            return self.body_template.format_map(_SafeDict(context))
        except Exception:
            return self.body_template
