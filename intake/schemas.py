"""Pydantic schemas for DraftContract.data validation.

One schema per contract_type. The `data` JSONField on `DraftContract` is
validated by `validate_data()` on every save — invalid payloads are rejected
at the model layer so the JSON-first architecture cannot rot over time.

All dates are stored as ISO-format strings (YYYY-MM-DD) in JSON. The schemas
declare them as `date`; pydantic parses both forms and round-trips to ISO.

Matched FK lifecycle: every parsed-text field that resolves to a FK keeps
both keys side-by-side (`*_text` + `*_id`). The `*_id` is None until the
analyst confirms a match via the matching modal; on finalization the `*_id`
becomes the real FK on the canonical contracts.* tables.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ---------------------------------------------------------------------------
# Common reusable pieces
# ---------------------------------------------------------------------------


class ParserProvenance(BaseModel):
    """Where the draft came from and how it was extracted."""

    model_config = ConfigDict(extra='allow')

    source: Optional[Literal['pdf', 'csv', 'dibbs', 'manual']] = None
    claude_used: Optional[bool] = None
    raw_extraction: Optional[str] = None
    parser_version: Optional[str] = None


class FinanceLine(BaseModel):
    """Quote-time finance line (special payment terms, progress payments, etc.)."""

    model_config = ConfigDict(extra='forbid')

    line_type: Optional[str] = None
    amount: Optional[Decimal] = None
    notes: Optional[str] = None


class Packaging(BaseModel):
    """Packhouse / packaging assignment captured during intake."""

    model_config = ConfigDict(extra='forbid')

    packhouse_cage: Optional[str] = None
    packhouse_supplier_text: Optional[str] = None
    packhouse_supplier_id: Optional[int] = None
    quote_amount: Optional[Decimal] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# CLIN row (used by AWD / PO / DO)
# ---------------------------------------------------------------------------


class DraftClin(BaseModel):
    model_config = ConfigDict(extra='forbid')

    item_number: Optional[str] = None
    item_type: Optional[str] = None  # P / G / C / L / M
    nsn_text: Optional[str] = None
    nsn_id: Optional[int] = None
    nsn_description: Optional[str] = None
    supplier_text: Optional[str] = None
    supplier_id: Optional[int] = None
    order_qty: Optional[float] = None
    uom: Optional[str] = None
    unit_price: Optional[Decimal] = None
    item_value: Optional[Decimal] = None
    due_date: Optional[date] = None
    ia: Optional[Literal['O', 'D']] = None
    fob: Optional[Literal['O', 'D']] = None


# ---------------------------------------------------------------------------
# IDIQ-specific sub-records
# ---------------------------------------------------------------------------


class ApprovedNsn(BaseModel):
    model_config = ConfigDict(extra='forbid')

    nsn_text: Optional[str] = None
    nsn_id: Optional[int] = None
    nsn_description: Optional[str] = None
    min_order_qty: Optional[str] = None


class ApprovedSupplier(BaseModel):
    model_config = ConfigDict(extra='forbid')

    supplier_text: Optional[str] = None
    supplier_id: Optional[int] = None
    cage: Optional[str] = None


# ---------------------------------------------------------------------------
# Per-type root schemas
# ---------------------------------------------------------------------------


class _CommonContractFields(BaseModel):
    """Fields shared across every type's `data` blob."""

    model_config = ConfigDict(extra='allow')

    award_date: Optional[date] = None
    due_date: Optional[date] = None
    contract_value: Optional[Decimal] = None
    solicitation_type: Optional[str] = None
    pr_number: Optional[str] = None
    buyer_text: Optional[str] = None
    buyer_id: Optional[int] = None
    contractor_name: Optional[str] = None
    contractor_cage: Optional[str] = None
    files_url: Optional[str] = None
    parser: Optional[ParserProvenance] = None


class AwdPoData(_CommonContractFields):
    """AWD (Award) and PO (Purchase Order) — same shape."""

    clins: List[DraftClin] = Field(default_factory=list)
    finance_lines: List[FinanceLine] = Field(default_factory=list)
    packaging: Optional[Packaging] = None


class DoData(AwdPoData):
    """Delivery Order — AWD/PO shape plus parent IDIQ reference."""

    parent_idiq_contract_number: Optional[str] = None
    parent_idiq_id: Optional[int] = None


class IdiqData(_CommonContractFields):
    """IDIQ — no CLINs; approved NSNs/suppliers plus term/option/max/min."""

    term_months: Optional[int] = None
    option_months: Optional[int] = None
    max_value: Optional[Decimal] = None
    min_guarantee: Optional[int] = None
    approved_nsns: List[ApprovedNsn] = Field(default_factory=list)
    approved_suppliers: List[ApprovedSupplier] = Field(default_factory=list)


class ModAmdData(_CommonContractFields):
    """Modification / Amendment — minimal shape; expanded as use cases land."""

    parent_contract_number: Optional[str] = None
    parent_contract_id: Optional[int] = None
    mod_number: Optional[str] = None
    summary: Optional[str] = None


class InternalData(_CommonContractFields):
    """Internal / non-DLA contracts. Flexible by design."""

    notes: Optional[str] = None
    clins: List[DraftClin] = Field(default_factory=list)


# Map contract_type → schema. Kept here so views / admin / tests can reuse.
SCHEMA_BY_TYPE = {
    'AWD': AwdPoData,
    'PO': AwdPoData,
    'DO': DoData,
    'IDIQ': IdiqData,
    'MOD': ModAmdData,
    'AMD': ModAmdData,
    'INTERNAL': InternalData,
}


class DraftDataValidationError(Exception):
    """Raised when DraftContract.data does not match its per-type schema."""

    def __init__(self, contract_type: str, errors: list):
        self.contract_type = contract_type
        self.errors = errors
        super().__init__(
            f'DraftContract.data failed validation for {contract_type}: {errors}'
        )


def validate_data(contract_type: str, data: dict) -> dict:
    """Validate `data` against the schema for `contract_type`.

    Returns the normalized dict (dates round-tripped to ISO strings, decimals
    preserved as strings for JSON storage). Raises DraftDataValidationError on
    any schema violation so callers can surface a clean error.
    """
    if not isinstance(data, dict):
        raise DraftDataValidationError(
            contract_type, [{'loc': (), 'msg': 'data must be a dict'}]
        )
    schema = SCHEMA_BY_TYPE.get(contract_type)
    if schema is None:
        raise DraftDataValidationError(
            contract_type,
            [{'loc': ('contract_type',), 'msg': f'unknown contract_type: {contract_type!r}'}],
        )
    try:
        instance = schema.model_validate(data)
    except ValidationError as exc:
        raise DraftDataValidationError(contract_type, exc.errors()) from exc
    return instance.model_dump(mode='json', exclude_none=False)
