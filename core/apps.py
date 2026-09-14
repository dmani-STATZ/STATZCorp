from django.apps import AppConfig
from django.conf import settings

_AZURE_MONITOR_CONFIGURED = False


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Production-only. The Azure Monitor OpenTelemetry distro instruments
        # Django, requests, and stdlib logging. Must run after Django applies
        # settings.LOGGING so dictConfig does not drop the distro's handler.
        global _AZURE_MONITOR_CONFIGURED
        if _AZURE_MONITOR_CONFIGURED:
            return
        if not getattr(settings, "APPLICATIONINSIGHTS_ENABLED", False):
            return
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.APPLICATIONINSIGHTS_CONNECTION_STRING,
        )
        _AZURE_MONITOR_CONFIGURED = True
