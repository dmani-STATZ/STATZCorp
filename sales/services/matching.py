"""
3-tier supplier matching engine and one-time contract history backfill.
Only reads from contracts in backfill_nsn_from_contracts(); matching uses dibbs_* tables only.
"""
import logging
from datetime import date
from decimal import Decimal

from django.db import transaction

from sales.models import (
    SolicitationLine,
    SupplierMatch,
    SupplierNSN,
    SupplierFSC,
    ApprovedSource,
    ImportBatch,
)
from suppliers.models import Supplier

logger = logging.getLogger(__name__)


def _normalize_nsn(nsn: str) -> str:
    """Strip hyphens and whitespace for consistent comparison."""
    return nsn.replace("-", "").strip() if nsn else ""


def _match_tier1_nsn(line: SolicitationLine) -> list[dict]:
    """
    Query dibbs_supplier_nsn for exact NSN match.
    Returns list of match dicts ordered by match_score desc.
    Excludes archived suppliers.
    """
    normalized = _normalize_nsn(line.nsn)
    if not normalized:
        return []

    qs = (
        SupplierNSN.objects.filter(nsn=normalized)
        .exclude(supplier__archived=True)
        .select_related("supplier")
        .order_by("-match_score")
    )
    return [
        {
            "supplier_id": row.supplier_id,
            "match_tier": 1,
            "match_method": "DIRECT_NSN",
            "match_score": row.match_score or Decimal("0"),
        }
        for row in qs
    ]


def _match_tier2_approved_source(line: SolicitationLine) -> list[dict]:
    """
    Find CAGEs in dibbs_approved_source for this NSN, then look up
    matching suppliers by cage_code in contracts_supplier.
    Excludes archived suppliers.
    """
    normalized = _normalize_nsn(line.nsn)
    if not normalized:
        return []

    cages = list(
        ApprovedSource.objects.filter(nsn=normalized).values_list(
            "approved_cage", flat=True
        ).distinct()
    )
    if not cages:
        return []

    suppliers = list(
        Supplier.objects.filter(
            cage_code__in=cages,
            archived=False,
        ).values_list("id", flat=True)
    )
    return [
        {
            "supplier_id": sid,
            "match_tier": 2,
            "match_method": "APPROVED_SOURCE",
            "match_score": Decimal("1.0"),
        }
        for sid in suppliers
    ]


def _match_tier3_fsc(line: SolicitationLine) -> list[dict]:
    """
    Match suppliers by FSC code (first 4 digits of NSN).
    Uses dibbs_supplier_fsc table.
    Excludes archived suppliers.
    """
    fsc = (line.fsc or "").strip()[:4]
    if not fsc:
        return []

    qs = (
        SupplierFSC.objects.filter(fsc_code=fsc)
        .exclude(supplier__archived=True)
        .values_list("supplier_id", flat=True)
        .distinct()
    )
    return [
        {
            "supplier_id": sid,
            "match_tier": 3,
            "match_method": "FSC",
            "match_score": Decimal("0.5"),
        }
        for sid in qs
    ]


def _deduplicate_matches(tier1: list[dict], tier2: list[dict], tier3: list[dict]) -> list[dict]:
    """
    Keep only the best (lowest tier number) match per supplier.
    """
    by_supplier = {}
    for m in tier1 + tier2 + tier3:
        sid = m["supplier_id"]
        if sid not in by_supplier or m["match_tier"] < by_supplier[sid]["match_tier"]:
            by_supplier[sid] = m
    return list(by_supplier.values())


def run_matching_for_batch(batch_id: int) -> dict:
    """
    Run all 3 matching tiers for every SolicitationLine in the given ImportBatch.
    OPTIMIZED: Batch all queries upfront instead of N+1 per-line queries.
    For a 2600-line import: ~4 queries instead of ~10,000.

    Clears existing SupplierMatch rows for those lines before re-matching
    (safe to re-run on the same batch).
    Returns summary: {lines_processed, matches_found, by_tier: {1: n, 2: n, 3: n}}
    """
    try:
        batch = ImportBatch.objects.get(pk=batch_id)
    except ImportBatch.DoesNotExist:
        logger.warning(f"ImportBatch id={batch_id} not found")
        return {
            "lines_processed": 0,
            "matches_found": 0,
            "by_tier": {1: 0, 2: 0, 3: 0},
        }

    # Fetch all lines for this batch
    lines = list(
        SolicitationLine.objects.filter(
            solicitation__import_batch=batch
        ).select_related("solicitation")
    )
    if not lines:
        return {
            "lines_processed": 0,
            "matches_found": 0,
            "by_tier": {1: 0, 2: 0, 3: 0},
        }

    line_ids = [ln.id for ln in lines]

    # Clear existing matches for these lines
    SupplierMatch.objects.filter(line_id__in=line_ids).delete()

    # ── BATCH TIER 1: Fetch all NSN matches upfront ──────────────
    # Build set of unique NSNs (excluding part-number items)
    nsn_to_lines = {}
    for line in lines:
        if line.item_type_indicator != "2":  # Skip part-number items
            normalized = _normalize_nsn(line.nsn)
            if normalized:
                nsn_to_lines.setdefault(normalized, []).append(line.id)

    # Single query: all SupplierNSN records for all NSNs
    tier1_matches = {}  # nsn → list of {supplier_id, match_score}
    if nsn_to_lines:
        tier1_rows = SupplierNSN.objects.filter(
            nsn__in=nsn_to_lines.keys()
        ).exclude(
            supplier__archived=True
        ).values("nsn", "supplier_id", "match_score")
        for row in tier1_rows:
            tier1_matches.setdefault(row["nsn"], []).append({
                "supplier_id": row["supplier_id"],
                "match_score": row["match_score"] or Decimal("0"),
            })

    # ── BATCH TIER 2: Fetch all ApprovedSource + Supplier matches ──
    # Build set of unique NSNs again for approved source lookups
    tier2_matches = {}  # nsn → list of supplier_ids
    if nsn_to_lines:
        # Single query: all approved cages for all NSNs
        approved_cages = {}
        for as_row in ApprovedSource.objects.filter(
            nsn__in=nsn_to_lines.keys()
        ).values_list("nsn", "approved_cage").distinct():
            nsn, cage = as_row
            approved_cages.setdefault(nsn, set()).add(cage)

        # Single query: all suppliers matching those cages
        if approved_cages:
            all_cages = set()
            for cages in approved_cages.values():
                all_cages.update(cages)
            suppliers_by_cage = {}
            for supplier in Supplier.objects.filter(
                cage_code__in=all_cages, archived=False
            ):
                suppliers_by_cage.setdefault(supplier.cage_code, []).append(supplier.id)

            # Build tier2_matches: nsn → supplier_ids
            for nsn, cages in approved_cages.items():
                supplier_ids = []
                for cage in cages:
                    supplier_ids.extend(suppliers_by_cage.get(cage, []))
                tier2_matches[nsn] = supplier_ids

    # ── BATCH TIER 3: Fetch all FSC matches upfront ────────────────
    # Build set of unique FSCs
    fsc_to_lines = {}
    for line in lines:
        fsc = (line.fsc or "").strip()[:4]
        if fsc:
            fsc_to_lines.setdefault(fsc, []).append(line.id)

    # Single query: all SupplierFSC records for all FSCs
    tier3_matches = {}  # fsc → list of supplier_ids
    if fsc_to_lines:
        for row in SupplierFSC.objects.filter(
            fsc_code__in=fsc_to_lines.keys()
        ).exclude(
            supplier__archived=True
        ).values_list("fsc_code", "supplier_id").distinct():
            fsc, supplier_id = row
            tier3_matches.setdefault(fsc, []).append(supplier_id)

    # ── Now match each line using the batched data ──────────────────
    by_tier = {1: 0, 2: 0, 3: 0}
    total_matches = 0
    to_create = []

    for line in lines:
        is_part_number = line.item_type_indicator == "2"
        normalized_nsn = _normalize_nsn(line.nsn)
        fsc = (line.fsc or "").strip()[:4]

        # Gather matches from our batched data (no DB queries!)
        tier1 = []
        if not is_part_number and normalized_nsn:
            for match in tier1_matches.get(normalized_nsn, []):
                tier1.append({
                    "supplier_id": match["supplier_id"],
                    "match_tier": 1,
                    "match_method": "DIRECT_NSN",
                    "match_score": match["match_score"],
                })

        tier2 = []
        if not is_part_number and normalized_nsn:
            for supplier_id in tier2_matches.get(normalized_nsn, []):
                tier2.append({
                    "supplier_id": supplier_id,
                    "match_tier": 2,
                    "match_method": "APPROVED_SOURCE",
                    "match_score": Decimal("1.0"),
                })

        tier3 = []
        if fsc:
            for supplier_id in tier3_matches.get(fsc, []):
                tier3.append({
                    "supplier_id": supplier_id,
                    "match_tier": 3,
                    "match_method": "FSC",
                    "match_score": Decimal("0.5"),
                })

        # Deduplicate and create SupplierMatch records
        combined = _deduplicate_matches(tier1, tier2, tier3)
        for m in combined:
            by_tier[m["match_tier"]] += 1
            to_create.append(
                SupplierMatch(
                    line_id=line.id,
                    supplier_id=m["supplier_id"],
                    match_tier=m["match_tier"],
                    match_method=m["match_method"],
                    match_score=m["match_score"],
                    is_excluded=False,
                )
            )
        total_matches += len(combined)

    if to_create:
        SupplierMatch.objects.bulk_create(to_create, batch_size=500)

    return {
        "lines_processed": len(lines),
        "matches_found": total_matches,
        "by_tier": by_tier,
    }


def backfill_nsn_from_contracts(dry_run: bool = False) -> dict:
    """
    One-time backfill of dibbs_supplier_nsn from contracts_clin history.

    - Groups CLINs by (nsn, supplier)
    - Calculates recency-weighted score per group
    - Upserts into dibbs_supplier_nsn with source='contract_history'
    - Does NOT overwrite records where source='manual'
    - dry_run=True: calculate and return counts without writing

    Returns: {processed, created, updated, skipped_manual, errors}
    """
    from contracts.models import Clin

    today = date.today()
    processed = 0
    created = 0
    updated = 0
    skipped_manual = 0
    errors = 0

    clins = (
        Clin.objects.exclude(supplier__is_packhouse=True)
        .exclude(supplier_id__isnull=True)
        .exclude(nsn_id__isnull=True)
        .select_related("contract", "supplier", "nsn")
    )

    # Group by (normalized_nsn, supplier_id) -> list of (award_date,)
    groups = {}
    for clin in clins:
        if not clin.contract or not clin.contract.award_date:
            continue
        nsn_raw = getattr(clin.nsn, "nsn_code", None) or ""
        normalized = _normalize_nsn(nsn_raw)
        if not normalized or not clin.supplier_id:
            continue
        key = (normalized, clin.supplier_id)
        award_dt = clin.contract.award_date
        award_date = award_dt.date() if hasattr(award_dt, "date") else award_dt
        groups.setdefault(key, []).append(award_date)
        processed += 1

    def _weight(age_years: float) -> float:
        if age_years <= 2:
            return 1.0
        if age_years <= 5:
            return 0.6
        if age_years <= 10:
            return 0.3
        return 0.1

    if dry_run:
        for (norm_nsn, supplier_id), dates in groups.items():
            score = sum(
                _weight((today - d).days / 365) for d in dates
            )
            existing = SupplierNSN.objects.filter(
                nsn=norm_nsn, supplier_id=supplier_id
            ).first()
            if existing:
                if existing.source == "manual":
                    skipped_manual += 1
                else:
                    updated += 1
            else:
                created += 1
        return {
            "processed": processed,
            "created": created,
            "updated": updated,
            "skipped_manual": skipped_manual,
            "errors": errors,
        }

    with transaction.atomic():
        for (norm_nsn, supplier_id), dates in groups.items():
            try:
                score = sum(
                    _weight((today - d).days / 365) for d in dates
                )
                existing = SupplierNSN.objects.filter(
                    nsn=norm_nsn, supplier_id=supplier_id
                ).first()
                if existing:
                    if existing.source == "manual":
                        skipped_manual += 1
                        continue
                    existing.match_score = Decimal(str(round(score, 2)))
                    existing.source = "contract_history"
                    existing.last_synced = today
                    existing.save()
                    updated += 1
                else:
                    SupplierNSN.objects.create(
                        supplier_id=supplier_id,
                        nsn=norm_nsn,
                        match_score=Decimal(str(round(score, 2))),
                        source="contract_history",
                        last_synced=today,
                    )
                    created += 1
            except Exception as e:
                logger.exception("backfill_nsn_from_contracts row error: %s", e)
                errors += 1

    return {
        "processed": processed,
        "created": created,
        "updated": updated,
        "skipped_manual": skipped_manual,
        "errors": errors,
    }
