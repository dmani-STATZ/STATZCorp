"""Match a parsed DFAS notice to one Contract and its SharePoint folder.

System job with no request: lookups are not scoped to a company.
See AGENTS_contracts.md.
"""
from __future__ import annotations

from django.db.models import F, Value
from django.db.models.functions import Replace, Upper

from contracts.models import Contract
from contracts.services.dfas_receipts.parser import ParsedNotice


class UnmatchedError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def find_contract(parsed: ParsedNotice) -> Contract:
    call_raw = (parsed.call_number_raw or '').strip()
    contract_base = parsed.contract_number_base or ''
    call_base = parsed.call_number_base or ''
    # No company filter. This job has no request.active_company.
    qs = Contract.objects.select_related('idiq_contract', 'status', 'company')
    if call_raw:
        if not call_base or not contract_base:
            raise UnmatchedError('contract_not_found')
        qs = qs.annotate(
            norm_contract=_normalized('contract_number'),
            norm_parent=_normalized('idiq_contract__contract_number'),
        ).filter(norm_contract=call_base, norm_parent=contract_base)
    else:
        if not contract_base:
            raise UnmatchedError('contract_not_found')
        qs = qs.annotate(
            norm_contract=_normalized('contract_number'),
        ).filter(norm_contract=contract_base)
    matches = list(qs)
    if not matches:
        raise UnmatchedError('contract_not_found')
    if len(matches) > 1:
        raise UnmatchedError('ambiguous_contract')
    return matches[0]


def resolve_target_folder(contract) -> str:
    from contracts.services.sharepoint_paths import (
        get_sharepoint_prefix,
        resolve_contract_folder_path,
    )
    from contracts.services.sharepoint_service import (
        SharePointNotFound,
        get_contract_documents_root,
        list_folder_contents,
        normalize_folder_path,
    )

    resolved = resolve_contract_folder_path(contract)
    path = normalize_folder_path((resolved or {}).get('path') or '')
    roots = {
        normalize_folder_path(get_contract_documents_root(contract)),
        normalize_folder_path(get_sharepoint_prefix(getattr(contract, 'company', None))),
    }
    if not path or path in roots:
        raise UnmatchedError('folder_missing')
    try:
        list_folder_contents(path)
    except SharePointNotFound:
        raise UnmatchedError('folder_missing')
    return path


def _normalized(field: str):
    return Upper(
        Replace(
            Replace(F(field), Value('-'), Value('')),
            Value(' '),
            Value(''),
        )
    )
