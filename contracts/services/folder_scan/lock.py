"""Run locking for folder scans."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from contracts.models_folder_scan import FolderScanRun
from contracts.services.folder_scan.exceptions import ScanAlreadyRunning

_STALE_MINUTES = 10


def acquire_run(
    root_path: str,
    started_by: str,
    apply_requested: bool,
    force: bool,
) -> FolderScanRun:
    """Create a new scan run or abandon a stale/conflicting running run."""
    root_path = (root_path or '').strip().strip('/')
    with transaction.atomic():
        running = (
            FolderScanRun.objects.select_for_update()
            .filter(root_path=root_path, status=FolderScanRun.Status.RUNNING)
            .first()
        )
        now = timezone.now()
        if running:
            heartbeat = running.heartbeat_at or running.started_at
            stale = (now - heartbeat).total_seconds() > _STALE_MINUTES * 60
            if not stale and not force:
                raise ScanAlreadyRunning(running.pk, running.heartbeat_at)
            running.status = FolderScanRun.Status.ABANDONED
            running.finished_at = now
            running.save(update_fields=['status', 'finished_at'])

        return FolderScanRun.objects.create(
            root_path=root_path,
            status=FolderScanRun.Status.RUNNING,
            started_by=started_by or '',
            apply_requested=apply_requested,
        )
