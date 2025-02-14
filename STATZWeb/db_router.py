# db_router.py
class MyAppRouter:
    # """
    # A router to control all database operations on models in the
# contracts application.
    # """
    def db_for_read(self, model, **hints):
        # """
        # Attempts to read contracts models go to ContractLog_Dev.
        # """
        if model._meta.app_label == 'contracts':
            return 'ContractLog_Dev'
        return None

    def db_for_write(self, model, **hints):
        # """
        # Attempts to write contracts models go to ContractLog_Dev.
        # """
        if model._meta.app_label == 'contracts':
            return 'ContractLog_Dev'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        # """
        # Allow relations if a model in contracts is involved.
        # """
        if obj1._meta.app_label == 'contracts' or obj2._meta.app_label == 'contracts':
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # """
        # Make sure the contracts app only appears in the 'ContractLog_Dev'
        # database.
        # """
        if app_label == 'contracts':
            return db == 'ContractLog_Dev'
        return None