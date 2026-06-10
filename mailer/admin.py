from django.contrib import admin
from .models import Campaign, CampaignRecipient

class CampaignRecipientInline(admin.TabularInline):
    model = CampaignRecipient
    extra = 0
    fields = ('email', 'first_name', 'company_name', 'status', 'sent_at')
    readonly_fields = ('status', 'sent_at')

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'sender_email', 'status', 'created_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'sender_email')
    inlines = [CampaignRecipientInline]

@admin.register(CampaignRecipient)
class CampaignRecipientAdmin(admin.ModelAdmin):
    list_display = ('email', 'campaign', 'first_name', 'company_name', 'status', 'sent_at')
    list_filter = ('status', 'campaign')
    search_fields = ('email', 'first_name', 'company_name')
