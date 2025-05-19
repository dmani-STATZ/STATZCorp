"""
Django app configuration for NLI reporting.
"""
from django.apps import AppConfig

class NLIReportingConfig(AppConfig):
    """Configuration for the NLI reporting app."""
    
    name = 'reports.nli_reporting'
    verbose_name = 'Natural Language Interface Reporting'
    
    def ready(self):
        """
        Perform any necessary initialization when the app is ready.
        """
        pass  # Add any initialization code here if needed 