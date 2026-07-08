"""Admin for DraftContract.

Admin is an escape hatch for staff cleanup and visibility — it is NOT the
analyst workflow. Stale locks (older than LOCK_DURATION) get a one-click
clear action; bulk clears live in `intake.management.commands.clear_stale_locks`.
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.utils.html import format_html

from .locks import LOCK_DURATION, is_expired
from .models import AwardLedger, DraftContract


class StaleLockFilter(admin.SimpleListFilter):
    title = 'lock state'
    parameter_name = 'lock_state'

    def lookups(self, request, model_admin):
        return (
            ('active', 'Active lock'),
            ('stale', 'Stale lock (expired)'),
            ('none', 'No lock'),
        )

    def queryset(self, request, queryset):
        from django.utils import timezone
        cutoff = timezone.now() - LOCK_DURATION
        if self.value() == 'active':
            return queryset.filter(locked_by__isnull=False, locked_at__gte=cutoff)
        if self.value() == 'stale':
            return queryset.filter(locked_by__isnull=False, locked_at__lt=cutoff)
        if self.value() == 'none':
            return queryset.filter(locked_by__isnull=True)
        return queryset


@admin.register(DraftContract)
class DraftContractAdmin(admin.ModelAdmin):
    list_display = (
        'contract_number',
        'company',
        'contract_type',
        'status',
        'sharepoint_folder_status',
        'lock_summary',
        'pdf_parse_status',
        'created_at',
        'final_contract',
    )
    list_filter = (
        'contract_type',
        'status',
        'company',
        'sharepoint_folder_status',
        'pdf_parse_status',
        StaleLockFilter,
    )
    search_fields = ('contract_number',)
    readonly_fields = ('created_at', 'modified_at', 'final_contract')
    actions = ('clear_locks',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('company', 'locked_by')

    def lock_summary(self, obj):
        if obj.locked_by_id is None:
            return '—'
        if is_expired(obj.locked_at):
            return format_html(
                '<span style="color:#b45309;">stale: {}</span>',
                obj.locked_by.username,
            )
        return format_html(
            '<span style="color:#0f766e;">held by {}</span>',
            obj.locked_by.username,
        )
    lock_summary.short_description = 'Lock'

    @admin.action(description='Clear lock on selected drafts')
    def clear_locks(self, request, queryset):
        updated = queryset.filter(locked_by__isnull=False).update(
            locked_by=None, locked_at=None
        )
        self.message_user(
            request,
            f'Cleared locks on {updated} draft(s).',
            level=messages.SUCCESS,
        )


@admin.register(AwardLedger)
class AwardLedgerAdmin(admin.ModelAdmin):
    """Read-mostly durable award-lifecycle ledger.

    All lifecycle timestamps and FK links are read-only — the ledger is
    maintained by the sweep service, not by hand.
    """

    list_display = (
        'contract_number',
        'lifecycle_state',
        'is_we_won',
        'has_award',
        'awardee_cage',
        'mod_count',
        'first_seen_at',
        'draft_created_at',
        'draft_worked_at',
        'live_contract_at',
    )
    list_filter = (
        'lifecycle_state',
        'is_we_won',
        'has_award',
        'awardee_cage',
    )
    search_fields = (
        'contract_number',
        'award_basic_number',
        'purchase_request',
    )
    readonly_fields = (
        'first_seen_at',
        'draft_created_at',
        'draft_worked_at',
        'mod_record_created_at',
        'live_contract_at',
        'updated_at',
        'dibbs_award',
        'contract',
    )
    date_hierarchy = 'first_seen_at'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('dibbs_award', 'contract')
