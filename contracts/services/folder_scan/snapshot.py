"""Snapshot load and write for folder scans."""

from contracts.models_folder_scan import FolderScanRun, ScannedFolder

_BULK_SIZE = 500


def load_index(root_path: str) -> dict[str, dict]:
    """Load the full drive index from the latest completed scan."""
    run = (
        FolderScanRun.objects.filter(root_path=root_path, status=FolderScanRun.Status.COMPLETED)
        .order_by('-started_at')
        .first()
    )
    if not run:
        return {}

    index = {}
    for folder in run.folders.values(
        'drive_item_id', 'parent_drive_item_id', 'name', 'web_url'
    ):
        index[folder['drive_item_id']] = {
            'id': folder['drive_item_id'],
            'parent_id': folder['parent_drive_item_id'],
            'name': folder['name'],
            'web_url': folder['web_url'],
        }
    return index


def write_snapshot(
    run: FolderScanRun,
    index: dict[str, dict],
    in_scope_ids: set[str],
    scoped: list[dict],
) -> None:
    """Write the full library index to ScannedFolder for the current run."""
    ScannedFolder.objects.filter(run=run).delete()

    objs = []

    # 1. In-scope folders
    for s in scoped:
        objs.append(
            ScannedFolder(
                run=run,
                drive_item_id=s['drive_item_id'],
                parent_drive_item_id=s['parent_drive_item_id'],
                name=s['name'],
                path=s['path'],
                depth=s['depth'],
                web_url=s['web_url'],
                folder_kind=s['folder_kind'],
                parsed_contract_number=s['parsed_contract_number'],
                normalized_contract_number=s['normalized_contract_number'],
                in_scope=True,
            )
        )

    # 2. Out-of-scope folders
    out_of_scope_ids = set(index.keys()) - in_scope_ids
    for oid in out_of_scope_ids:
        item = index[oid]
        objs.append(
            ScannedFolder(
                run=run,
                drive_item_id=item['id'],
                parent_drive_item_id=item['parent_id'],
                name=item['name'],
                path='',
                depth=0,
                web_url=item['web_url'],
                folder_kind=ScannedFolder.FolderKind.OTHER,
                match_status=ScannedFolder.MatchStatus.NOT_CONTRACT_FOLDER,
                in_scope=False,
            )
        )

    for i in range(0, len(objs), _BULK_SIZE):
        ScannedFolder.objects.bulk_create(objs[i : i + _BULK_SIZE])

    run.folders_saved = len(objs)
