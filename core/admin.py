from django.contrib import admin
from .models import APIBudget, APIUsageLog

@admin.register(APIBudget)
class APIBudgetAdmin(admin.ModelAdmin):
    list_display = ['balance_usd', 'last_sync_amount', 'last_sync_at', 'updated_at']
    readonly_fields = ['updated_at']

@admin.register(APIUsageLog)
class APIUsageLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'call_site', 'model', 'input_tokens', 'output_tokens', 'cost_usd']
    list_filter = ['model', 'call_site']
    readonly_fields = ['timestamp', 'call_site', 'model', 'input_tokens', 'output_tokens', 'cost_usd']
