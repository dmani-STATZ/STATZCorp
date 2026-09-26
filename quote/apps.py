from django.apps import AppConfig


class QuoteConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quote'
    verbose_name = 'Quotes (DIBBS Quoting)'

    def ready(self):
        from . import signals  # noqa: F401  (connects the dibbs receivers)
