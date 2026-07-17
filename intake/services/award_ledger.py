"""Award Intake Ledger sweep service.

Maintains ``intake.AwardLedger`` — the durable, one-row-per-contract-identity
record of the DIBBS award → intake draft → live-contract lifecycle. Because
``DraftContract.final_contract`` is deleted together with the draft on
finalization, this ledger is the ONLY persistent record of that journey.

Conventions (mirror ``intake.services.queue_we_won_drafts``):
  - Module logger + ``_LOG_PREFIX``.
  - Lazy cross-app imports inside functions (intake → sales, intake →
    contracts). No ``processing.*`` imports.
  - NEVER raise to callers. Every public entry point wraps its body in a
    try/except and logs; scrapes, polls, and finalization must never be
    aborted by a ledger failure.
  - MSSQL / pyodbc has no MARS: materialize every source read with
    ``list(qs.values(...))`` (or ``list(qs)``) before issuing any secondary
    DB call on the same connection. No raw SQL.

Latching invariant: the ``*_at`` lifecycle timestamps are write-once — every
set goes through ``_latch`` which only writes when the field is currently
``None``. ``lifecycle_state`` is recomputed each sweep but may only advance.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Optional

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[award_ledger]"

# Chunk size for ``__in`` lookups — stays well under SQL Server's 2,100
# parameter limit while keeping round-trips low.
_IN_CHUNK = 500


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _chunked(seq: list, size: int = _IN_CHUNK) -> Iterable[list]:
    """Yield successive ``size``-length slices of ``seq``."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _latch(row, field: str, value) -> bool:
    """Set ``field`` on ``row`` only if it is currently ``None``.

    Returns True when a write occurred (the value changed), False otherwise.
    This is the single guard behind the write-once latching invariant.
    """
    if getattr(row, field) is None:
        setattr(row, field, value)
        return True
    return False


def _canonical(record_or_number) -> str:
    """Return the canonical (dashed) contract number.

    Accepts either a raw string or a DIBBS-shaped mapping (with
    ``delivery_order_number`` / ``award_basic_number``). Returns '' when the
    input yields no usable identity.
    """
    from contracts.services.contract_number import canonicalize_contract_number

    if isinstance(record_or_number, dict):
        do = (record_or_number.get("delivery_order_number") or "").strip()
        basic = (record_or_number.get("award_basic_number") or "").strip()
        raw = do or basic
    else:
        raw = record_or_number
    if not raw:
        return ""
    return canonicalize_contract_number(raw) or ""


def _s(value) -> str:
    """Coerce a possibly-None value to a stripped string (never None)."""
    return "" if value is None else str(value)


def _compute_lifecycle(row) -> str:
    """Return the furthest lifecycle stage observed for ``row``."""
    from intake.models import AwardLedger

    LC = AwardLedger.Lifecycle
    if row.live_contract_at is not None:
        return LC.LIVE_CONTRACT
    if row.draft_worked_at is not None:
        return LC.DRAFT_WORKED
    if row.draft_created_at is not None:
        return LC.IN_DRAFT
    if row.is_we_won:
        return LC.AWAITING_DRAFT
    if row.mod_record_created_at is not None:
        return LC.MOD_ONLY
    return LC.NOT_WE_WON


def _advance_state(row) -> bool:
    """Recompute ``lifecycle_state``, advancing only (never regressing).

    Returns True when the state moved forward.
    """
    from intake.models import AwardLedger

    rank = AwardLedger.LIFECYCLE_RANK
    target = _compute_lifecycle(row)
    current = row.lifecycle_state or ""
    if rank.get(target, -1) > rank.get(current, -1):
        row.lifecycle_state = target
        return True
    return False


def _apply_award_mirror(row, award: dict) -> None:
    """Copy mirror fields from a materialized DibbsAward ``.values()`` dict."""
    row.award_basic_number = _s(award.get("award_basic_number"))
    row.delivery_order_number = _s(award.get("delivery_order_number"))
    row.delivery_order_counter = _s(award.get("delivery_order_counter"))
    row.awardee_cage = _s(award.get("awardee_cage"))
    row.nsn = _s(award.get("nsn"))
    row.nomenclature = _s(award.get("nomenclature"))
    row.purchase_request = _s(award.get("purchase_request"))
    row.solicitation = _s(award.get("sol_number"))
    row.total_contract_price = award.get("total_contract_price")
    row.award_date = award.get("award_date")
    row.posted_date = award.get("posted_date")
    row.aw_file_date = award.get("aw_file_date")
    # last_mod_posting_date is refreshed here if the award carries one; the
    # mod loop may advance it further.
    if award.get("last_mod_posting_date") is not None:
        row.last_mod_posting_date = award.get("last_mod_posting_date")


def _apply_mod_mirror(row, mod: dict) -> None:
    """Fill mirror fields from a mod when no award has populated them yet.

    Award data always wins; a mod only backfills empty/None mirror columns so
    a mod-only ledger row (award not yet imported) still has useful context.
    """
    if not row.award_basic_number:
        row.award_basic_number = _s(mod.get("award_basic_number"))
    if not row.delivery_order_number:
        row.delivery_order_number = _s(mod.get("delivery_order_number"))
    if not row.delivery_order_counter:
        row.delivery_order_counter = _s(mod.get("delivery_order_counter"))
    if not row.awardee_cage:
        row.awardee_cage = _s(mod.get("awardee_cage"))
    if not row.nsn:
        row.nsn = _s(mod.get("nsn"))
    if not row.nomenclature:
        row.nomenclature = _s(mod.get("nomenclature"))
    if not row.purchase_request:
        row.purchase_request = _s(mod.get("purchase_request"))
    if not row.solicitation:
        row.solicitation = _s(mod.get("sol_number"))
    if row.posted_date is None:
        row.posted_date = mod.get("posted_date")
    if row.aw_file_date is None:
        row.aw_file_date = mod.get("aw_file_date")


# ---------------------------------------------------------------------------
# Batch sweep
# ---------------------------------------------------------------------------


def upsert_ledger_for_batch(
    batch,
    activity_log: Optional[Callable[[str], None]] = None,
    source: str = 'legacy',
) -> dict:
    """Upsert ledger rows for every our-CAGE award and mod in ``batch``.

    For each ``DibbsAward`` whose awardee CAGE is one of our active CAGEs and
    each ``DibbsAwardMod`` whose base contract is our-CAGE:
      - ``get_or_create`` the ledger row keyed by canonical contract number,
      - refresh the DIBBS mirror fields,
      - set ``has_award`` / ``dibbs_award`` / ``is_we_won`` (award ∈ WeWonAward),
      - refresh ``mod_count`` and latch ``mod_record_created_at`` when a mod
        exists,
      - latch ``draft_created_at`` from an existing ``DraftContract``,
      - advance ``lifecycle_state``.

    Then reconciles the touched rows (draft-worked proxy + live-contract
    backstop). Returns counts ``{created, updated, we_won, mods}``. Never
    raises to the caller.
    """
    emit: Callable[[str], None] = activity_log or (lambda _m: None)

    def _emit(msg: str) -> None:
        line = f"{_LOG_PREFIX} {msg}"
        logger.info(line)
        emit(line)

    result = {"created": 0, "updated": 0, "we_won": 0, "mods": 0}

    if batch is None:
        _emit("skip: batch is None")
        return result

    try:
        from sales.models import (
            CompanyCAGE,
            DibbsAward,
            DibbsAwardMod,
            WeWonAward,
        )
        from intake.models import AwardLedger, DraftContract

        # -- Materialize every source read up front (no MARS) --------------
        our_cages = {
            (c or "").strip().upper()
            for c in CompanyCAGE.objects.filter(is_active=True).values_list(
                "cage_code", flat=True
            )
            if (c or "").strip()
        }
        if not our_cages:
            _emit(f"batch_id={batch.pk}: no active CompanyCAGE codes — nothing to do")
            return result

        award_fields = (
            "id", "award_basic_number", "delivery_order_number",
            "delivery_order_counter", "awardee_cage", "nsn", "nomenclature",
            "purchase_request", "sol_number", "total_contract_price",
            "award_date", "posted_date", "aw_file_date", "last_mod_posting_date",
        )
        awards = list(
            DibbsAward.objects.filter(
                aw_import_batch=batch,
                awardee_cage__in=our_cages,
            ).values(*award_fields)
        )

        mod_fields = (
            "award_basic_number", "delivery_order_number",
            "delivery_order_counter", "awardee_cage", "nsn", "nomenclature",
            "purchase_request", "sol_number", "mod_date", "posted_date",
            "aw_file_date",
        )
        mods = list(
            DibbsAwardMod.objects.filter(
                aw_import_batch=batch,
                awardee_cage__in=our_cages,
            ).values(*mod_fields)
        )

        # We-won award ids within this batch (single subquery, materialized).
        we_won_ids = set(
            DibbsAward.objects.filter(
                aw_import_batch=batch,
                id__in=WeWonAward.objects.values("id"),
            ).values_list("id", flat=True)
        )

        # Group mods by canonical contract identity.
        mods_by_cn: dict[str, list[dict]] = {}
        for mod in mods:
            cn = _canonical(mod)
            if not cn:
                continue
            mods_by_cn.setdefault(cn, []).append(mod)

        # Pre-fetch existing drafts for every contract number we may touch.
        touched_cns: set[str] = set()
        for award in awards:
            cn = _canonical(award)
            if cn:
                touched_cns.add(cn)
        touched_cns.update(mods_by_cn.keys())

        draft_map = _draft_info_map(DraftContract, list(touched_cns))

        now = timezone.now()

        # -- Awards --------------------------------------------------------
        for award in awards:
            cn = _canonical(award)
            if not cn:
                continue
            row, created = AwardLedger.objects.get_or_create(
                contract_number=cn,
                defaults={"first_seen_at": now},
            )
            _apply_award_mirror(row, award)
            row.has_award = True
            row.dibbs_award_id = award["id"]
            if award["id"] in we_won_ids:
                row.is_we_won = True
                result["we_won"] += 1

            cn_mods = mods_by_cn.get(cn, [])
            if cn_mods:
                _apply_mod_summary(row, cn_mods, now)

            draft = draft_map.get(cn)
            if draft is not None:
                _latch(row, "draft_created_at", draft["created_at"])

            if not row.ingestion_source:
                row.ingestion_source = source

            _advance_state(row)
            row.save()
            result["created" if created else "updated"] += 1

        # -- Mod-only rows (identities with a mod but no award this batch) --
        award_cns = {_canonical(a) for a in awards if _canonical(a)}
        for cn, cn_mods in mods_by_cn.items():
            result["mods"] += len(cn_mods)
            if cn in award_cns:
                continue  # already handled in the award loop above
            row, created = AwardLedger.objects.get_or_create(
                contract_number=cn,
                defaults={"first_seen_at": now},
            )
            # Only backfill mirror fields; award data (if it arrives later)
            # will win on the next sweep.
            _apply_mod_mirror(row, cn_mods[0])
            _apply_mod_summary(row, cn_mods, now)

            draft = draft_map.get(cn)
            if draft is not None:
                _latch(row, "draft_created_at", draft["created_at"])

            if not row.ingestion_source:
                row.ingestion_source = source

            _advance_state(row)
            row.save()
            result["created" if created else "updated"] += 1

        _emit(
            f"batch_id={batch.pk}: created={result['created']} "
            f"updated={result['updated']} we_won={result['we_won']} "
            f"mods={result['mods']}"
        )

        # Reconcile just the rows we touched (draft-worked + live backstop).
        if touched_cns:
            reconcile_open_ledger_rows(
                activity_log=activity_log,
                contract_numbers=list(touched_cns),
            )

    except Exception as exc:  # never crash the caller
        result["errors"] = result.get("errors", 0) + 1
        _emit(f"fatal error: {exc}")
        logger.exception("%s fatal error in upsert_ledger_for_batch", _LOG_PREFIX)

    return result


def _apply_mod_summary(row, cn_mods: list[dict], now) -> None:
    """Refresh mod_count / last_mod_posting_date and latch mod timestamp.

    ``mod_count`` is monotonic non-decreasing (``max`` of the current value and
    the number of mods seen this sweep) so re-running a batch never inflates it.
    """
    row.mod_count = max(row.mod_count or 0, len(cn_mods))
    mod_dates = [m.get("mod_date") for m in cn_mods if m.get("mod_date") is not None]
    if mod_dates:
        latest = max(mod_dates)
        if row.last_mod_posting_date is None or latest > row.last_mod_posting_date:
            row.last_mod_posting_date = latest
    _latch(row, "mod_record_created_at", now)


def _draft_info_map(DraftContract, cns: list[str]) -> dict[str, dict]:
    """Return {contract_number: draft-info dict} for the given numbers.

    Chunked ``__in`` to respect the SQL Server 2,100-parameter limit.
    """
    out: dict[str, dict] = {}
    for chunk in _chunked(cns):
        if not chunk:
            continue
        rows = DraftContract.objects.filter(contract_number__in=chunk).values(
            "contract_number", "status", "locked_by_id",
            "created_at", "modified_at",
        )
        for d in rows:
            out[d["contract_number"]] = d
    return out


# ---------------------------------------------------------------------------
# Open-row reconciliation
# ---------------------------------------------------------------------------


def reconcile_open_ledger_rows(
    activity_log: Optional[Callable[[str], None]] = None,
    contract_numbers: Optional[list[str]] = None,
) -> dict:
    """Reconcile open ledger rows against drafts and canonical contracts.

    A row is "open" when ``live_contract_at IS NULL`` OR (``draft_created_at``
    is set AND ``draft_worked_at`` is NULL). For each open row (optionally
    scoped to ``contract_numbers``):

      - draft_worked proxy: if a ``DraftContract`` still exists and is
        non-``queued`` OR has ``locked_by`` set OR ``modified_at >
        created_at`` → latch ``draft_worked_at``.
      - live_contract backstop: if a ``contracts.Contract`` exists with that
        number → latch ``live_contract_at`` and set the ``contract`` FK when
        unset.
      - advance ``lifecycle_state``.

    Returns counts ``{scanned, draft_worked, live}``. Never raises.
    """
    emit: Callable[[str], None] = activity_log or (lambda _m: None)

    def _emit(msg: str) -> None:
        line = f"{_LOG_PREFIX} {msg}"
        logger.info(line)
        emit(line)

    result = {"scanned": 0, "draft_worked": 0, "live": 0}

    try:
        from contracts.models import Contract
        from intake.models import AwardLedger, DraftContract

        open_q = Q(live_contract_at__isnull=True) | Q(
            draft_created_at__isnull=False, draft_worked_at__isnull=True
        )
        qs = AwardLedger.objects.filter(open_q)
        if contract_numbers is not None:
            # Scope with chunked __in, materializing each chunk.
            rows: list = []
            for chunk in _chunked(list(contract_numbers)):
                if not chunk:
                    continue
                rows.extend(list(qs.filter(contract_number__in=chunk)))
        else:
            rows = list(qs)  # materialize model instances (no open cursor)

        now = timezone.now()

        # Process in chunks so the secondary __in lookups stay bounded.
        for chunk in _chunked(rows):
            cns = [r.contract_number for r in chunk]
            draft_map = _draft_info_map(DraftContract, cns)
            contract_map = _contract_id_map(Contract, cns)

            for row in chunk:
                result["scanned"] += 1
                changed = False

                draft = draft_map.get(row.contract_number)
                if draft is not None and row.draft_worked_at is None:
                    worked = (
                        draft["status"] != DraftContract.Status.QUEUED
                        or draft["locked_by_id"] is not None
                        or (
                            draft["modified_at"] is not None
                            and draft["created_at"] is not None
                            and draft["modified_at"] > draft["created_at"]
                        )
                    )
                    if worked and _latch(row, "draft_worked_at", now):
                        changed = True
                        result["draft_worked"] += 1

                contract_id = contract_map.get(row.contract_number)
                if contract_id is not None:
                    if _latch(row, "live_contract_at", now):
                        changed = True
                        result["live"] += 1
                    if row.contract_id is None:
                        row.contract_id = contract_id
                        changed = True

                if _advance_state(row):
                    changed = True

                if changed:
                    row.save()

        _emit(
            f"reconcile: scanned={result['scanned']} "
            f"draft_worked={result['draft_worked']} live={result['live']}"
        )

    except Exception as exc:  # never crash the caller
        result["errors"] = result.get("errors", 0) + 1
        _emit(f"fatal error: {exc}")
        logger.exception("%s fatal error in reconcile_open_ledger_rows", _LOG_PREFIX)

    return result


def _contract_id_map(Contract, cns: list[str]) -> dict[str, int]:
    """Return {contract_number: id} for canonical contracts, chunked ``__in``."""
    out: dict[str, int] = {}
    for chunk in _chunked(cns):
        if not chunk:
            continue
        rows = Contract.objects.filter(contract_number__in=chunk).values(
            "contract_number", "id"
        )
        for c in rows:
            out[c["contract_number"]] = c["id"]
    return out


# ---------------------------------------------------------------------------
# Real-time finalize hook
# ---------------------------------------------------------------------------


def stamp_live_contract(contract_number: str, contract, user=None) -> None:
    """Latch ``live_contract_at`` when a draft finalizes into a live contract.

    Called from ``intake.finalize`` inside the finalize transaction, right
    where the canonical Contract has been created. No-op when the ledger has
    no row for this number (non-DIBBS manual drafts are out of ledger scope).
    Never raises — a ledger failure must never abort finalization.
    """
    try:
        from intake.models import AwardLedger

        cn = _canonical(contract_number)
        if not cn:
            return
        row = AwardLedger.objects.filter(contract_number=cn).first()
        if row is None:
            return

        changed = _latch(row, "live_contract_at", timezone.now())
        if user is not None:
            if _latch(row, "finalized_by", user):
                changed = True
        if row.contract_id is None and contract is not None:
            row.contract_id = contract.pk
            changed = True
        if _advance_state(row):
            changed = True
        if changed:
            row.save()
    except Exception:
        logger.exception(
            "%s stamp_live_contract failed for %r", _LOG_PREFIX, contract_number
        )


def log_draft_ingestion(draft, source: str, user=None) -> None:
    """Ensure a ledger row exists the moment a draft enters intake.

    get_or_create on _canonical(draft.contract_number); latch first_seen_at
    and draft_created_at; latch ingestion_source (first-touch); latch
    created_by; populate awardee_cage per D3 when creating a non-DIBBS row;
    then reconcile the row. Guarded end-to-end — never raises to the caller.
    """
    try:
        from intake.models import AwardLedger

        cn = _canonical(draft.contract_number)
        if not cn:
            return

        now = timezone.now()
        row, created = AwardLedger.objects.get_or_create(
            contract_number=cn,
            defaults={"first_seen_at": now},
        )

        changed = False

        if _latch(row, "draft_created_at", draft.created_at or now):
            changed = True

        if not row.ingestion_source:
            row.ingestion_source = source
            changed = True

        if user is not None:
            if _latch(row, "created_by", user):
                changed = True

        # D3: CAGE resolution order
        if not row.awardee_cage:
            cage = (draft.data or {}).get("contractor_cage")
            if cage:
                row.awardee_cage = str(cage).strip().upper()
                changed = True
            else:
                if draft.company:
                    from sales.models import CompanyCAGE
                    active_cages = list(
                        CompanyCAGE.objects.filter(
                            company=draft.company, is_active=True
                        ).values_list("cage_code", flat=True)
                    )
                    if len(active_cages) == 1:
                        row.awardee_cage = active_cages[0].strip().upper()
                        changed = True
                    elif len(active_cages) > 1:
                        logger.warning(
                            "%s log_draft_ingestion: company %s has multiple active CAGE codes %s — cannot auto-assign CAGE for draft %s",
                            _LOG_PREFIX, draft.company.pk, active_cages, draft.pk
                        )
                if not row.awardee_cage:
                    logger.warning(
                        "%s log_draft_ingestion: could not resolve CAGE for draft %s (number %s)",
                        _LOG_PREFIX, draft.pk, draft.contract_number
                    )

        if _advance_state(row):
            changed = True

        if changed:
            row.save()

        # Reconcile just this row
        reconcile_open_ledger_rows(
            activity_log=None,
            contract_numbers=[cn],
        )

    except Exception:
        logger.exception(
            "%s log_draft_ingestion failed for draft %s (number %s)",
            _LOG_PREFIX, getattr(draft, "pk", None), getattr(draft, "contract_number", None)
        )
