"""
Supplier creation helpers for ad-hoc RFQ dispatch.
Used when a CAGE code from DIBBS data is not yet in our supplier DB.
"""
from suppliers.models import Supplier


def create_supplier_from_sam(sam_data: dict, email: str = '') -> tuple:
    """
    Find or create a Supplier from a SAM.gov lookup result.

    sam_data: dict returned by lookup_cage() when found=True.
    email: optional contact email (SAM entity data doesn't include email addresses).

    Returns (supplier, created).
    Never overwrites an existing supplier's data.
    """
    cage = sam_data['cage_code']

    existing = Supplier.objects.filter(cage_code=cage).first()
    if existing:
        return (existing, False)

    set_asides = ', '.join(
        k for k, v in sam_data.get('set_aside_flags', {}).items() if v
    ) or 'None'
    notes = (
        f"[SAM] Registered: {sam_data['registration_status']} | "
        f"Expires: {sam_data.get('registration_expiry', 'N/A')} | "
        f"UEI: {sam_data.get('uei', '')} | "
        f"Set-asides: {set_asides}"
    )

    supplier = Supplier.objects.create(
        name=sam_data['legal_name'],
        cage_code=cage,
        business_email=email if email else None,
        notes=notes,
        archived=False,
        probation=False,
        conditional=False,
    )
    return (supplier, True)


def get_or_create_stub_supplier(
    cage_code: str = '',
    name: str = '',
    email: str = '',
    phone: str = '',
) -> tuple:
    """
    Fallback when SAM.gov is unavailable or returns no result.

    If cage_code is provided and matches an existing supplier, returns it unchanged.
    Otherwise creates a minimal stub with [STUB] in notes.

    Returns (supplier, created).
    """
    if cage_code:
        existing = Supplier.objects.filter(cage_code=cage_code).first()
        if existing:
            return (existing, False)

    resolved_name = name or (f"CAGE {cage_code}" if cage_code else "Unknown Supplier")

    create_kwargs = dict(
        name=resolved_name,
        business_email=email if email else None,
        notes='[STUB] Created from DIBBS RFQ dispatch — complete profile in Suppliers.',
        archived=False,
        probation=False,
        conditional=False,
    )
    if cage_code:
        create_kwargs['cage_code'] = cage_code

    supplier = Supplier.objects.create(**create_kwargs)
    return (supplier, True)
