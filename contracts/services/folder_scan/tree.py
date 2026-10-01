"""Tree building and diffing for folder scan index."""

from collections import deque

from contracts.services.folder_scan.normalize import normalize_contract_number, parse_folder_name


def apply_item(index: dict[str, dict], kind: str, rec: dict) -> None:
    """Apply a classified Graph delta item to the library index."""
    if kind == 'folder':
        index[rec['id']] = rec
    elif kind == 'deleted':
        index.pop(rec['id'], None)


def build_scoped_tree(
    index: dict[str, dict],
    root_id: str,
    root_path: str,
) -> tuple[list[dict], set[str]]:
    """Build tree paths for the scan root and return in-scope items and their ids."""
    children = {}
    for item in index.values():
        pid = item['parent_id']
        children.setdefault(pid, []).append(item)

    scoped = []
    in_scope_ids = set()

    if root_id not in index:
        return scoped, in_scope_ids

    root_folder_path = f"{root_path.rstrip('/')}/"
    queue = deque([(root_id, root_folder_path, 0)])
    visited = set()

    while queue:
        item_id, path, depth = queue.popleft()

        if item_id in visited:
            continue
        visited.add(item_id)

        item = index[item_id]
        in_scope_ids.add(item_id)

        folder_kind, raw = parse_folder_name(item['name'])
        scoped.append({
            'drive_item_id': item_id,
            'parent_drive_item_id': item['parent_id'],
            'name': item['name'],
            'path': path,
            'depth': depth,
            'web_url': item['web_url'],
            'folder_kind': folder_kind,
            'parsed_contract_number': raw,
            'normalized_contract_number': normalize_contract_number(raw),
        })

        for child in children.get(item_id, []):
            child_path = f"{path.rstrip('/')}/{child['name']}/"
            queue.append((child['id'], child_path, depth + 1))

    return scoped, in_scope_ids


def diff_scoped(old: dict[str, str], new: dict[str, str]) -> tuple[int, int, int]:
    """Return counts of (added, changed, removed) paths."""
    old_ids = set(old.keys())
    new_ids = set(new.keys())

    added = len(new_ids - old_ids)
    removed = len(old_ids - new_ids)
    changed = sum(1 for i in (old_ids & new_ids) if old[i] != new[i])

    return added, changed, removed
