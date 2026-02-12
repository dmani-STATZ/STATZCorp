from django.apps import AppConfig


class TransactionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "transactions"
    verbose_name = "Field change transactions"

    def ready(self):
        import transactions.signals  # noqa: F401
