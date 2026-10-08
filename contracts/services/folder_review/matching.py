"""Pure string matching helpers for folder review pair suggestions."""

from __future__ import annotations


def within_one_edit(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = [i for i in range(la) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            i, j = diffs
            return a[i] == b[j] and a[j] == b[i] and a[:i] == b[:i] and a[j + 1 :] == b[j + 1 :]
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = j = 0
    used_skip = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        elif not used_skip:
            used_skip = True
            j += 1
        else:
            return False
    return True


def edit_distance_capped(a: str, b: str, cap: int = 2) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > cap:
        return cap + 1
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        row_min = curr[0]
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ai == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            )
            if (
                i > 1
                and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                curr[j] = min(curr[j], prev[j - 2] + 1)
            row_min = min(row_min, curr[j])
        if row_min > cap:
            return cap + 1
        prev = curr
    dist = prev[lb]
    return dist if dist <= cap else cap + 1


def _edge_distance(folder_norm: str, contract_norm: str) -> int | None:
    if within_one_edit(folder_norm, contract_norm):
        return 1
    if len(folder_norm) >= 12 and len(contract_norm) >= 12:
        if folder_norm[:6] != contract_norm[:6]:
            return None
        if edit_distance_capped(folder_norm, contract_norm, 2) == 2:
            return 2
    return None


def suggest_pairs(contracts: list[dict], folders: list[dict]) -> list[dict]:
    """Mutually best unique contract↔folder edges by normalized number distance."""
    folder_best: dict[str, tuple[int, int, int]] = {}
    contract_best: dict[int, tuple[int, str, int]] = {}

    for folder in folders:
        fid = folder.get('drive_item_id') or ''
        fn = folder.get('normalized') or ''
        if not fid or not fn:
            continue
        for contract in contracts:
            cid = contract.get('id')
            cn = contract.get('normalized') or ''
            if cid is None or not cn:
                continue
            dist = _edge_distance(fn, cn)
            if dist is None:
                continue
            prev_f = folder_best.get(fid)
            if prev_f is None or dist < prev_f[0] or (dist == prev_f[0] and cid < prev_f[1]):
                folder_best[fid] = (dist, cid, contract.get('contract_number_sort') or 0)
            prev_c = contract_best.get(cid)
            if prev_c is None or dist < prev_c[0] or (dist == prev_c[0] and fid < prev_c[1]):
                contract_best[cid] = (dist, fid, contract.get('contract_number_sort') or 0)

    folder_ties: dict[str, int] = {}
    contract_ties: dict[int, int] = {}
    for folder in folders:
        fid = folder.get('drive_item_id') or ''
        fn = folder.get('normalized') or ''
        if not fid or not fn:
            continue
        best_dist = folder_best.get(fid, (999, 0, 0))[0]
        count = 0
        for contract in contracts:
            cn = contract.get('normalized') or ''
            cid = contract.get('id')
            if cid is None or not cn:
                continue
            dist = _edge_distance(fn, cn)
            if dist is not None and dist == best_dist:
                count += 1
        if count > 1:
            folder_ties[fid] = count

    for contract in contracts:
        cid = contract.get('id')
        cn = contract.get('normalized') or ''
        if cid is None or not cn:
            continue
        best_dist = contract_best.get(cid, (999, '', 0))[0]
        count = 0
        for folder in folders:
            fn = folder.get('normalized') or ''
            fid = folder.get('drive_item_id') or ''
            if not fid or not fn:
                continue
            dist = _edge_distance(fn, cn)
            if dist is not None and dist == best_dist:
                count += 1
        if count > 1:
            contract_ties[cid] = count

    edges: list[dict] = []
    for folder in folders:
        fid = folder.get('drive_item_id') or ''
        if not fid or fid in folder_ties:
            continue
        fb = folder_best.get(fid)
        if fb is None:
            continue
        dist, cid, _ = fb
        cb = contract_best.get(cid)
        if cb is None or cb[0] != dist or cb[1] != fid:
            continue
        if cid in contract_ties:
            continue
        edges.append(
            {
                'contract_id': cid,
                'contract_number': folder.get('_pair_contract_number'),
                'drive_item_id': fid,
                'folder_name': folder.get('name') or '',
                'folder_path': folder.get('path') or '',
                'folder_web_url': folder.get('web_url') or '',
                'distance': dist,
                'contract_status': folder.get('_pair_contract_status') or '',
                'contract_files_url': folder.get('_pair_contract_files_url') or '',
            }
        )

    contract_by_id = {c['id']: c for c in contracts if c.get('id') is not None}
    for edge in edges:
        c = contract_by_id.get(edge['contract_id'])
        if c:
            edge['contract_number'] = c.get('contract_number') or ''
            edge['contract_status'] = c.get('status') or ''
            edge['contract_files_url'] = c.get('files_url') or ''

    edges.sort(
        key=lambda row: (
            row['distance'],
            row.get('contract_number') or '',
            row.get('folder_name') or '',
        )
    )
    return edges
