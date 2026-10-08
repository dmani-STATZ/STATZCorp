"""Folder Review Stage B — SharePoint repairs (audited)."""

from __future__ import annotations

import re
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser

from contracts.models import Contract, IdiqContract
from contracts.models_folder_scan import FolderRepairLog, ScannedFolder
from contracts.services.drive_item_lookup import (
    get_folder_path_by_item_id,
    invalidate_item_path_cache,
)
from contracts.services.folder_scan.normalize import normalize_contract_number, parse_folder_name
from contracts.services.folder_review.queues import (
    CLOSED_MOVE_STATUSES,
    build_move_closed_candidates,
    load_review_context,
)
from contracts.services.folder_review.sharepoint_writes import (
    WriteConflict,
    WriteFailed,
    WriteLocked,
    WriteNotFound,
    duplicate_retry_name,
    list_children_all,
    merged_loser_name,
    move_item,
    rename_item,
    resolve_path_to_id,
)
from contracts.services.sharepoint_paths import format_stored_files_url, is_modern_sharepoint_path

WRITES_DISABLED = "SharePoint writes are disabled"
MERGED_PREFIX = "MERGED - "
_CHILD_MOVE_LIMIT = 100
_MOVE_CLOSED_MAX = 50


def _writes_enabled() -> bool:
    return bool(getattr(settings, "FOLDER_REVIEW_SHAREPOINT_WRITES", False))


def _disabled() -> dict:
    return {"ok": False, "message": WRITES_DISABLED}


def _normalize_display_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").casefold()).strip()


def _expected_name_contract(c: Contract) -> str:
    if c.idiq_contract_id:
        return f"Delivery Order {c.contract_number}"
    return f"Contract {c.contract_number}"


def _expected_name_idiq(i: IdiqContract) -> str:
    return f"Contract {i.contract_number}"


def _latest_run(root_path: str):
    from contracts.services.folder_review.queues import _latest_completed_run

    return _latest_completed_run(root_path)


def _scan_row(run, drive_item_id: str) -> ScannedFolder | None:
    if not run or not drive_item_id:
        return None
    return (
        ScannedFolder.objects.filter(
            run=run,
            in_scope=True,
            drive_item_id=drive_item_id,
        )
        .select_related("contract", "contract__company", "idiq_contract", "idiq_contract__company")
        .first()
    )


def _write_log(**kwargs) -> FolderRepairLog:
    return FolderRepairLog.objects.create(**kwargs)


def _apply_record_path(
    *,
    contract: Contract | None,
    idiq: IdiqContract | None,
    drive_item_id: str,
    live_path: str,
    actor: AbstractBaseUser,
) -> tuple[str, str]:
    new_url = format_stored_files_url(live_path)
    company = (contract.company if contract else None) or (idiq.company if idiq else None)
    if not is_modern_sharepoint_path(new_url, company=company):
        raise WriteFailed("Path failed modern SharePoint validation.", status=400)

    if contract:
        old_url = contract.files_url or ""
        old_drive = contract.sharepoint_drive_item_id or ""
        contract.files_url = new_url
        contract.sharepoint_drive_item_id = drive_item_id
        contract._drive_item_id_confirmed = True
        contract.modified_by = actor
        contract.save(
            update_fields=[
                "files_url",
                "sharepoint_drive_item_id",
                "modified_by",
                "modified_on",
            ]
        )
        return old_url, old_drive

    if idiq is None:
        raise WriteFailed("Record not found.", status=400)
    old_url = idiq.files_url or ""
    old_drive = idiq.sharepoint_drive_item_id or ""
    idiq.files_url = new_url
    idiq.sharepoint_drive_item_id = drive_item_id
    idiq._drive_item_id_confirmed = True
    idiq.save()
    return old_url, old_drive


def _refresh_snapshot_matched(
    snap: ScannedFolder,
    *,
    live_path: str,
    name: str,
    contract: Contract | None = None,
    idiq: IdiqContract | None = None,
) -> None:
    kind, raw = parse_folder_name(name)
    snap.name = name
    snap.path = live_path
    snap.folder_kind = kind if kind in (
        ScannedFolder.FolderKind.CONTRACT,
        ScannedFolder.FolderKind.DELIVERY_ORDER,
    ) else ScannedFolder.FolderKind.OTHER
    snap.parsed_contract_number = raw or ""
    snap.normalized_contract_number = normalize_contract_number(raw) if raw else ""
    snap.match_status = ScannedFolder.MatchStatus.MATCHED_EXPECTED
    snap.files_url_at_scan = format_stored_files_url(live_path)
    if contract:
        snap.contract = contract
        snap.idiq_contract = None
    elif idiq:
        snap.idiq_contract = idiq
        snap.contract = None
    snap.save(
        update_fields=[
            "name",
            "path",
            "folder_kind",
            "parsed_contract_number",
            "normalized_contract_number",
            "match_status",
            "files_url_at_scan",
            "contract",
            "idiq_contract",
        ]
    )


def _refresh_snapshot_renamed_loser(snap: ScannedFolder, *, live_path: str, name: str) -> None:
    kind, raw = parse_folder_name(name)
    snap.name = name
    snap.path = live_path
    if kind in (ScannedFolder.FolderKind.CONTRACT, ScannedFolder.FolderKind.DELIVERY_ORDER):
        snap.folder_kind = kind
    else:
        snap.folder_kind = ScannedFolder.FolderKind.OTHER
    snap.parsed_contract_number = raw or ""
    snap.normalized_contract_number = normalize_contract_number(raw) if raw else ""
    snap.match_status = ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER
    snap.save(
        update_fields=[
            "name",
            "path",
            "folder_kind",
            "parsed_contract_number",
            "normalized_contract_number",
            "match_status",
        ]
    )


def rename_to_expected(
    record_type: str,
    record_id: int,
    root_path: str,
    actor: AbstractBaseUser,
) -> dict:
    if not _writes_enabled():
        return _disabled()

    run = _latest_run(root_path)
    if run is None:
        return {"ok": False, "message": "No completed scan yet."}

    record_type = (record_type or "").strip().lower()

    contract = None
    idiq = None
    drive_item_id = ""
    expected = ""

    if record_type == "contract":
        contract = Contract.objects.select_related("company", "idiq_contract").filter(pk=record_id).first()
        if contract is None:
            return {"ok": False, "message": "Contract not found."}
        drive_item_id = (contract.sharepoint_drive_item_id or "").strip()
        expected = _expected_name_contract(contract)
    elif record_type == "idiq":
        idiq = IdiqContract.objects.select_related("company").filter(pk=record_id).first()
        if idiq is None:
            return {"ok": False, "message": "IDIQ not found."}
        drive_item_id = (idiq.sharepoint_drive_item_id or "").strip()
        expected = _expected_name_idiq(idiq)
    else:
        return {"ok": False, "message": "record_type must be contract or idiq."}

    snap = _scan_row(run, drive_item_id)
    if snap is None:
        return {"ok": False, "message": "Folder not in latest scan."}

    current_name = snap.name or ""
    if _normalize_display_name(current_name) == _normalize_display_name(expected):
        return {"ok": True, "message": "Name already correct.", "done": [], "skipped": []}

    ctx = load_review_context(root_path)
    allowed = {
        (row["record_type"], row["record_id"])
        for row in ctx._queues.get("name_mismatch", [])
    }
    key = ("contract" if record_type == "contract" else "idiq", int(record_id))
    if key not in allowed:
        return {"ok": False, "message": "Not in name-mismatch queue."}

    live = get_folder_path_by_item_id(drive_item_id)
    if live is None:
        return {"ok": False, "message": "Folder no longer exists or is unreachable."}

    old_url = (contract.files_url if contract else idiq.files_url) or ""
    old_drive = drive_item_id

    try:
        result = rename_item(drive_item_id, expected)
    except WriteConflict:
        return {
            "ok": True,
            "message": "Some items skipped.",
            "done": [],
            "skipped": [
                {
                    "item": drive_item_id,
                    "reason": (
                        f"A folder named '{expected}' already exists here; likely a duplicate. "
                        "Check the Duplicates tab."
                    ),
                }
            ],
        }
    except (WriteLocked, WriteNotFound, WriteFailed) as exc:
        return {"ok": False, "message": exc.message}

    new_name = result.get("name") or expected
    invalidate_item_path_cache(drive_item_id)
    live = get_folder_path_by_item_id(drive_item_id)
    if live is None:
        return {"ok": False, "message": "Could not re-read folder path after rename."}

    new_url, _ = _apply_record_path(
        contract=contract,
        idiq=idiq,
        drive_item_id=drive_item_id,
        live_path=live,
        actor=actor,
    )
    _refresh_snapshot_matched(
        snap,
        live_path=live,
        name=new_name,
        contract=contract,
        idiq=idiq,
    )
    _write_log(
        action=FolderRepairLog.Action.RENAME,
        contract=contract,
        idiq_contract=idiq,
        drive_item_id=drive_item_id,
        old_files_url=old_url,
        new_files_url=new_url,
        old_drive_item_id=old_drive,
        new_drive_item_id=drive_item_id,
        performed_by=actor,
    )
    return {
        "ok": True,
        "message": f"Renamed to {expected}.",
        "done": [{"item_id": drive_item_id, "path": live}],
        "skipped": [],
    }


def move_to_closed(
    contract_ids: list[int],
    root_path: str,
    actor: AbstractBaseUser,
    *,
    dry_run: bool = False,
) -> dict:
    if not dry_run and not _writes_enabled():
        return _disabled()

    if len(contract_ids) > _MOVE_CLOSED_MAX:
        return {"ok": False, "message": f"At most {_MOVE_CLOSED_MAX} contracts per request."}

    run = _latest_run(root_path)
    if run is None:
        return {"ok": False, "message": "No completed scan yet."}

    candidates = build_move_closed_candidates(root_path)
    eligible_ids = {int(row["contract_id"]) for row in candidates}
    closed_folder_id = resolve_path_to_id(f"{root_path.strip().strip('/')}/Closed Contracts")
    if not closed_folder_id and not dry_run:
        return {"ok": False, "message": "Closed Contracts folder not found."}

    done: list[dict] = []
    skipped: list[dict] = []

    for cid in contract_ids:
        cid = int(cid)
        if cid not in eligible_ids:
            skipped.append({"item": str(cid), "reason": "not eligible"})
            continue

        contract = Contract.objects.select_related("company").filter(pk=cid).first()
        if contract is None:
            skipped.append({"item": str(cid), "reason": "not eligible"})
            continue

        drive_item_id = (contract.sharepoint_drive_item_id or "").strip()
        snap = _scan_row(run, drive_item_id)
        if snap is None:
            skipped.append({"item": str(cid), "reason": "not eligible"})
            continue

        live = get_folder_path_by_item_id(drive_item_id) if not dry_run else (snap.path or "")
        if not dry_run and live is None:
            skipped.append({"item": str(cid), "reason": "folder missing"})
            continue

        if live and "/closed contracts/" in live.casefold():
            skipped.append({"item": str(cid), "reason": "already moved"})
            continue

        if dry_run:
            target_path = f"{root_path.strip().strip('/')}/Closed Contracts/{snap.name or ''}".rstrip("/") + "/"
            done.append(
                {
                    "contract_id": cid,
                    "old_path": snap.path or "",
                    "new_path": target_path,
                }
            )
            continue

        old_url = contract.files_url or ""
        old_drive = drive_item_id
        try:
            move_item(drive_item_id, closed_folder_id)
        except WriteConflict:
            skipped.append(
                {
                    "item": str(cid),
                    "reason": "name exists in Closed Contracts (duplicate?)",
                }
            )
            continue
        except WriteLocked:
            skipped.append(
                {
                    "item": str(cid),
                    "reason": "folder or a file in it is locked/open",
                }
            )
            continue
        except (WriteNotFound, WriteFailed) as exc:
            skipped.append({"item": str(cid), "reason": exc.message})
            continue

        invalidate_item_path_cache(drive_item_id)
        live = get_folder_path_by_item_id(drive_item_id)
        if live is None:
            skipped.append({"item": str(cid), "reason": "path unreadable after move"})
            continue

        new_url, _ = _apply_record_path(
            contract=contract,
            idiq=None,
            drive_item_id=drive_item_id,
            live_path=live,
            actor=actor,
        )
        _refresh_snapshot_matched(
            snap,
            live_path=live,
            name=snap.name or "",
            contract=contract,
        )
        _write_log(
            action=FolderRepairLog.Action.MOVE_CLOSED,
            contract=contract,
            drive_item_id=drive_item_id,
            old_files_url=old_url,
            new_files_url=new_url,
            old_drive_item_id=old_drive,
            new_drive_item_id=drive_item_id,
            performed_by=actor,
        )
        done.append({"contract_id": cid, "old_path": snap.path or "", "new_path": live})

    return {
        "ok": True,
        "message": f"Moved {len(done)}; skipped {len(skipped)}.",
        "done": done,
        "skipped": skipped,
    }


def _duplicate_group_db_id(record_type: str, record_id: int, root_path: str) -> tuple[str, dict | None]:
    ctx = load_review_context(root_path)
    for group in ctx._queues.get("ready_to_merge", []):
        rt = (group.get("record_type") or "").lower()
        rid = group.get("record_id")
        if rt == record_type and int(rid) == int(record_id):
            return (group.get("winner_drive_item_id") or "").strip(), group
    return "", None


def preview_merge(record_type: str, record_id: int, root_path: str) -> dict:
    record_type = (record_type or "").strip().lower()
    winner_id, group = _duplicate_group_db_id(record_type, record_id, root_path)
    if not winner_id or group is None:
        return {"ok": False, "message": "Pick the real folder first (Stage A)."}

    try:
        winner_children = list_children_all(winner_id)
    except WriteFailed as exc:
        return {"ok": False, "message": exc.message}

    winner_names = {(c.get("name") or "") for c in winner_children}
    losers = []
    for loser in group.get("losers") or []:
        lid = loser.get("drive_item_id") or ""
        if not lid:
            continue
        try:
            children = list_children_all(lid)
        except WriteFailed as exc:
            return {"ok": False, "message": exc.message}
        planned = []
        for child in children:
            name = child.get("name") or ""
            planned.append(
                {
                    "id": child.get("id") or "",
                    "name": name,
                    "destination_name": name,
                    "conflict": name in winner_names,
                }
            )
        losers.append(
            {
                "loser_id": lid,
                "loser_path": loser.get("path") or "",
                "children": planned,
            }
        )
    return {
        "ok": True,
        "winner_path": group.get("winner_path") or "",
        "losers": losers,
    }


def merge_duplicates(
    record_type: str,
    record_id: int,
    root_path: str,
    actor: AbstractBaseUser,
) -> dict:
    if not _writes_enabled():
        return _disabled()

    record_type = (record_type or "").strip().lower()
    winner_id, group = _duplicate_group_db_id(record_type, record_id, root_path)
    if not winner_id or group is None:
        return {"ok": False, "message": "Pick the real folder first (Stage A)."}

    run = _latest_run(root_path)
    if run is None:
        return {"ok": False, "message": "No completed scan yet."}

    contract = None
    idiq = None
    if record_type == "contract":
        contract = Contract.objects.filter(pk=record_id).first()
    elif record_type == "idiq":
        idiq = IdiqContract.objects.filter(pk=record_id).first()

    done: list[dict] = []
    skipped: list[dict] = []
    moved = 0
    remaining = 0

    loser_rows = list(group.get("losers") or [])
    for loser in loser_rows:
        if moved >= _CHILD_MOVE_LIMIT:
            break
        lid = (loser.get("drive_item_id") or "").strip()
        if not lid or lid == winner_id:
            continue

        live_name = loser.get("live_name") or loser.get("name") or ""
        if live_name.startswith(MERGED_PREFIX):
            continue

        live_path = get_folder_path_by_item_id(lid)
        if live_path is None:
            skipped.append({"item": lid, "reason": "loser missing"})
            continue

        try:
            children = list_children_all(lid)
        except WriteFailed as exc:
            skipped.append({"item": lid, "reason": exc.message})
            continue

        if not children:
            original = live_name or loser.get("name") or ""
            new_name = merged_loser_name(original)
            try:
                rename_item(lid, new_name)
            except (WriteConflict, WriteLocked, WriteNotFound, WriteFailed) as exc:
                reason = getattr(exc, "message", str(exc))
                skipped.append({"item": lid, "reason": reason})
                continue
            invalidate_item_path_cache(lid)
            live = get_folder_path_by_item_id(lid)
            snap = _scan_row(run, lid)
            if snap and live:
                _refresh_snapshot_renamed_loser(snap, live_path=live, name=new_name)
            _write_log(
                action=FolderRepairLog.Action.MERGE_COMPLETE,
                contract=contract,
                idiq_contract=idiq,
                drive_item_id=lid,
                detail=f"merged into {winner_id}",
                performed_by=actor,
            )
            done.append({"item_id": lid, "action": "merge_complete"})
            continue

        child_index = 0
        while child_index < len(children) and moved < _CHILD_MOVE_LIMIT:
            child = children[child_index]
            child_index += 1
            child_id = child.get("id") or ""
            child_name = child.get("name") or ""
            is_folder = "folder" in child
            if not child_id:
                continue
            try:
                move_item(child_id, winner_id)
            except WriteConflict:
                retry_name = duplicate_retry_name(child_name, is_folder=is_folder)
                try:
                    move_item(child_id, winner_id, new_name=retry_name)
                except WriteConflict:
                    skipped.append({"item": child_id, "reason": "name conflict"})
                    continue
                except (WriteLocked, WriteNotFound, WriteFailed) as exc:
                    skipped.append({"item": child_id, "reason": exc.message})
                    continue
            except WriteLocked:
                skipped.append({"item": child_id, "reason": "locked"})
                continue
            except (WriteNotFound, WriteFailed) as exc:
                skipped.append({"item": child_id, "reason": exc.message})
                continue

            moved += 1
            loser_path = loser.get("path") or live_path or ""
            _write_log(
                action=FolderRepairLog.Action.MERGE_MOVE,
                contract=contract,
                idiq_contract=idiq,
                drive_item_id=child_id,
                detail=f"{child_name} from {loser_path}",
                performed_by=actor,
            )
            done.append({"item_id": child_id, "action": "merge_move"})

        try:
            remaining_children = list_children_all(lid)
        except WriteFailed:
            remaining_children = children[child_index:]

        if not remaining_children and moved < _CHILD_MOVE_LIMIT:
            original = live_name or loser.get("name") or ""
            if not original.startswith(MERGED_PREFIX):
                new_name = merged_loser_name(original)
                try:
                    rename_item(lid, new_name)
                    invalidate_item_path_cache(lid)
                    live = get_folder_path_by_item_id(lid)
                    snap = _scan_row(run, lid)
                    if snap and live:
                        _refresh_snapshot_renamed_loser(snap, live_path=live, name=new_name)
                    _write_log(
                        action=FolderRepairLog.Action.MERGE_COMPLETE,
                        contract=contract,
                        idiq_contract=idiq,
                        drive_item_id=lid,
                        detail=f"merged into {winner_id}",
                        performed_by=actor,
                    )
                    done.append({"item_id": lid, "action": "merge_complete"})
                except (WriteConflict, WriteLocked, WriteNotFound, WriteFailed) as exc:
                    reason = getattr(exc, "message", str(exc))
                    skipped.append({"item": lid, "reason": reason})

    for loser in loser_rows:
        lid = (loser.get("drive_item_id") or "").strip()
        if not lid or lid == winner_id:
            continue
        name = loser.get("live_name") or loser.get("name") or ""
        if name.startswith(MERGED_PREFIX):
            continue
        try:
            children = list_children_all(lid)
        except WriteFailed:
            continue
        remaining += len(children)

    if contract or idiq:
        winner_snap = _scan_row(run, winner_id)
        if winner_snap:
            live = get_folder_path_by_item_id(winner_id) or winner_snap.path or ""
            _refresh_snapshot_matched(
                winner_snap,
                live_path=live,
                name=winner_snap.name or "",
                contract=contract,
                idiq=idiq,
            )

    return {
        "ok": True,
        "message": f"Moved {moved} item(s).",
        "done": done,
        "skipped": skipped,
        "remaining": remaining,
    }


def move_do_to_idiq(
    contract_id: int,
    root_path: str,
    actor: AbstractBaseUser,
) -> dict:
    if not _writes_enabled():
        return _disabled()

    ctx = load_review_context(root_path)
    allowed = {int(row["contract_id"]) for row in ctx._queues.get("do_mismatch", []) if row.get("contract_id")}
    if int(contract_id) not in allowed:
        return {"ok": False, "message": "Not in DO mismatch queue."}

    contract = Contract.objects.select_related("company", "idiq_contract").filter(pk=contract_id).first()
    if contract is None or not contract.idiq_contract_id:
        return {"ok": False, "message": "Contract or IDIQ missing."}

    idiq = contract.idiq_contract
    idiq_folder_id = (idiq.sharepoint_drive_item_id or "").strip()
    if not idiq_folder_id:
        return {"ok": False, "message": "IDIQ has no stored drive item id."}

    do_folder_id = (contract.sharepoint_drive_item_id or "").strip()
    run = _latest_run(root_path)
    if run is None:
        return {"ok": False, "message": "No completed scan yet."}

    snap = _scan_row(run, do_folder_id)
    if snap is None:
        alt = (
            ScannedFolder.objects.filter(
                run=run,
                in_scope=True,
                contract_id=contract.id,
            )
            .values("drive_item_id")
            .first()
        )
        if alt:
            do_folder_id = (alt.get("drive_item_id") or "").strip()
            snap = _scan_row(run, do_folder_id)

    if not do_folder_id or snap is None:
        return {"ok": False, "message": "DO folder not found in scan."}

    if do_folder_id == idiq_folder_id:
        return {"ok": False, "message": "DO folder is already under the IDIQ folder id."}

    live = get_folder_path_by_item_id(do_folder_id)
    if live is None:
        return {"ok": False, "message": "DO folder no longer exists."}

    old_url = contract.files_url or ""
    old_drive = do_folder_id
    try:
        move_item(do_folder_id, idiq_folder_id)
    except WriteConflict:
        return {
            "ok": True,
            "message": "Skipped.",
            "done": [],
            "skipped": [{"item": do_folder_id, "reason": "name conflict under IDIQ"}],
        }
    except WriteLocked:
        return {
            "ok": True,
            "message": "Skipped.",
            "done": [],
            "skipped": [{"item": do_folder_id, "reason": "folder or file locked"}],
        }
    except (WriteNotFound, WriteFailed) as exc:
        return {"ok": False, "message": exc.message}

    invalidate_item_path_cache(do_folder_id)
    live = get_folder_path_by_item_id(do_folder_id)
    if live is None:
        return {"ok": False, "message": "Could not re-read path after move."}

    new_url, _ = _apply_record_path(
        contract=contract,
        idiq=None,
        drive_item_id=do_folder_id,
        live_path=live,
        actor=actor,
    )
    _refresh_snapshot_matched(
        snap,
        live_path=live,
        name=snap.name or "",
        contract=contract,
    )
    _write_log(
        action=FolderRepairLog.Action.MOVE_DO,
        contract=contract,
        drive_item_id=do_folder_id,
        old_files_url=old_url,
        new_files_url=new_url,
        old_drive_item_id=old_drive,
        new_drive_item_id=do_folder_id,
        detail=f"under IDIQ {idiq.contract_number}",
        performed_by=actor,
    )
    return {
        "ok": True,
        "message": "Delivery order folder moved under IDIQ.",
        "done": [{"item_id": do_folder_id, "path": live}],
        "skipped": [],
    }
