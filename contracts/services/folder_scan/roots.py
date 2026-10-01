"""Resolve SharePoint scan roots from company configuration."""

from __future__ import annotations

from django.conf import settings

from contracts.models import Company


def resolve_company_root(company) -> str:
    """Return the drive-relative scan root for a company (no trailing slash)."""
    path = (getattr(company, 'sharepoint_documents_path', None) or '').strip()
    if not path:
        path = (getattr(settings, 'SHAREPOINT_PATH_PREFIX', None) or '').strip()
    return path.strip().strip('/')


def roots_to_company_ids() -> dict[str, list[int]]:
    """Map each resolved root path to every company PK that uses it."""
    rows = list(Company.objects.values('id', 'sharepoint_documents_path'))
    mapping: dict[str, list[int]] = {}
    for row in rows:
        company = Company(
            id=row['id'],
            sharepoint_documents_path=row.get('sharepoint_documents_path') or '',
        )
        root = resolve_company_root(company)
        if not root:
            continue
        mapping.setdefault(root, []).append(row['id'])
    for root in mapping:
        mapping[root] = sorted(mapping[root])
    return mapping
