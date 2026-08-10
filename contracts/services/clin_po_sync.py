"""
contracts/services/clin_po_sync.py

Keep Contract.po_number and every Clin.clin_po_num under that contract in sync.

Call `sync_po_number` from `transaction_edit_field` after a successful save of
either field. Propagation lives in the view layer (not signals) so propagated
`.save()` calls only fire audit history — they do not re-enter this logic.

Field landmines (do not confuse):
  - Clin.clin_po_num  — UI "Sub PO #"; THIS is the CLIN field we sync
  - Clin.po_number    — legacy / unused; NEVER read or write here
  - Contract.po_number — UI "PO Number" on the contract header; THIS is the
    contract field we sync
  - Contract.prime_po_number — unrelated
  - contracts.PurchaseOrder.po_number — PO Generator feature; unrelated

Each propagated write uses its own `.save(update_fields=[...])` so
transactions.signals creates a separate Transaction row. Never use
QuerySet.update().

Returns a dict of what was actually updated (equality-guard skipped writes
are omitted):
  {
    'contract_po_number': <str|None>,   # present only if Contract was written
    'clins': [{'clin_id': int, 'clin_po_num': <str|None>}, ...],
  }
"""

from contracts.models import Clin


def sync_po_number(instance, new_value, request_user) -> dict:
    """
    Propagate a PO number change across the contract and its CLINs.
    `instance` is the Contract or Clin that was just saved as the primary edit.
    """
    updated = {"clins": []}
    kind = type(instance).__name__

    if kind == "Clin":
        if not instance.contract_id:
            return updated

        contract = instance.contract
        if contract is not None and contract.po_number != new_value:
            contract.po_number = new_value
            contract.modified_by = request_user
            contract.save(update_fields=["po_number", "modified_by", "modified_on"])
            updated["contract_po_number"] = new_value

        siblings = Clin.objects.filter(contract_id=instance.contract_id).exclude(
            pk=instance.pk
        )
        for sibling in siblings:
            if sibling.clin_po_num == new_value:
                continue
            sibling.clin_po_num = new_value
            sibling.modified_by = request_user
            sibling.save(update_fields=["clin_po_num", "modified_by", "modified_on"])
            updated["clins"].append(
                {"clin_id": sibling.pk, "clin_po_num": new_value}
            )

    elif kind == "Contract":
        for clin in Clin.objects.filter(contract_id=instance.pk):
            if clin.clin_po_num == new_value:
                continue
            clin.clin_po_num = new_value
            clin.modified_by = request_user
            clin.save(update_fields=["clin_po_num", "modified_by", "modified_on"])
            updated["clins"].append(
                {"clin_id": clin.pk, "clin_po_num": new_value}
            )

    return updated
