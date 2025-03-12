from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import Contract, Clin, Note, Reminder

User = get_user_model()

class ActiveUserAdminMixin:
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in ['assigned_user', 'reviewed_by', 'reminder_user', 'reminder_completed_user']:
            kwargs['queryset'] = User.objects.filter(is_active=True).order_by('username')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(Contract)
class ContractAdmin(ActiveUserAdminMixin, admin.ModelAdmin):
    list_display = ['contract_number', 'po_number', 'status', 'assigned_user', 'reviewed_by']
    search_fields = ['contract_number', 'po_number']
    list_filter = ['status', 'assigned_user', 'reviewed_by']

@admin.register(Reminder)
class ReminderAdmin(ActiveUserAdminMixin, admin.ModelAdmin):
    list_display = ['reminder_title', 'reminder_date', 'reminder_user', 'reminder_completed']
    search_fields = ['reminder_title', 'reminder_text']
    list_filter = ['reminder_completed', 'reminder_user']
