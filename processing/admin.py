# processing/admin.py
from django.contrib import admin
from django.db import transaction
from django.contrib import messages
from .models import (
    QueueContract,
    QueueClin,
    ProcessContract,
    ProcessClin,
    ProcessClinSplit,
)


@admin.register(ProcessClinSplit)
class ProcessClinSplitAdmin(admin.ModelAdmin):
    list_display = ('id', 'clin', 'company_name', 'split_value', 'split_paid')
    list_filter = ('company_name',)
    search_fields = ('company_name',)
    raw_id_fields = ('clin',)

# Action function to perform the force delete
@admin.action(description='Force delete selected contracts and all related data')
def force_delete_contracts(modeladmin, request, queryset):
    """
    Admin action to forcefully delete QueueContract and all associated data
    across QueueClin, ProcessContract, ProcessClin, and ProcessClinSplit.
    """
    deleted_count = 0
    related_deleted_counts = {
        'QueueClin': 0,
        'ProcessContract': 0,
        'ProcessClin': 0,
        'ProcessClinSplit': 0,
    }

    # We use a transaction to ensure atomicity - either everything gets deleted or nothing does.
    try:
        with transaction.atomic():
            for qc in queryset:
                qc_id = qc.id
                contract_number = qc.contract_number # Store for message

                # 1. Delete related QueueClins
                qclins_deleted, _ = QueueClin.objects.filter(queue_contract=qc).delete()
                related_deleted_counts['QueueClin'] += qclins_deleted

                # 2. Find and delete related ProcessContract and its children
                pc = ProcessContract.objects.filter(queue_id=qc_id).first()
                if pc:
                    pc_id = pc.id
                    related_deleted_counts['ProcessClinSplit'] += ProcessClinSplit.objects.filter(
                        clin__process_contract_id=pc_id
                    ).count()
                    pclins_deleted, _ = ProcessClin.objects.filter(process_contract_id=pc_id).delete()
                    related_deleted_counts['ProcessClin'] += pclins_deleted
                    pc.delete()
                    related_deleted_counts['ProcessContract'] += 1

                # 3. Delete the QueueContract
                qc.delete()
                deleted_count += 1

                modeladmin.message_user(
                    request,
                    f"Successfully force-deleted QueueContract '{contract_number}' and its related data.",
                    messages.SUCCESS
                )

    except Exception as e:
        modeladmin.message_user(
            request,
            f"An error occurred during deletion: {e}. No contracts were deleted in this batch.",
            messages.ERROR
        )
    else:
        # Optional: Add a summary message if multiple were deleted
        if deleted_count > 1:
             modeladmin.message_user(
                request,
                 f"Total QueueContracts deleted: {deleted_count}. Related items deleted: "
                 f"QueueClins({related_deleted_counts['QueueClin']}), "
                 f"ProcessContracts({related_deleted_counts['ProcessContract']}), "
                 f"ProcessClins({related_deleted_counts['ProcessClin']}), "
                 f"ProcessClinSplits({related_deleted_counts['ProcessClinSplit']}).",
                messages.INFO
             )

# Customize the QueueContract admin
class QueueContractAdmin(admin.ModelAdmin):
    list_display = ('contract_number', 'buyer', 'award_date', 'due_date', 'is_being_processed', 'processed_by')
    list_filter = ('is_being_processed', 'buyer')
    search_fields = ('contract_number', 'buyer', 'contract_details')
    actions = [force_delete_contracts] # Add the custom action here

    # Make fields read-only to prevent accidental edits in this specific admin view
    # You might want to keep some editable depending on your workflow
    readonly_fields = [field.name for field in QueueContract._meta.fields]

    def has_add_permission(self, request):
        # Disable adding QueueContracts directly from this admin page
        return False

    def has_change_permission(self, request, obj=None):
        # Allow viewing but prevent changing via the standard form
        # Changes should happen via the processing workflow or force delete action
        # If you want to allow some changes, adjust this logic
        return False # Set to True if you want the change form accessible (but fields are read-only above)


# Register your models here
admin.site.register(QueueContract, QueueContractAdmin)
