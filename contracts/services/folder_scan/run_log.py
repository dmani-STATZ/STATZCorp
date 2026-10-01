"""Buffered logging for folder scan runs."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, TextIO

from django.utils import timezone

from contracts.models_folder_scan import FolderScanLog, FolderScanRun


class ScanLogger:
    """Write scan progress to stdout and FolderScanLog rows."""

    def __init__(self, run: FolderScanRun, stdout: TextIO | None = None) -> None:
        self.run = run
        self.stdout = stdout
        self._buffer: list[FolderScanLog] = []
        self._last_flush = time.monotonic()

    def info(self, msg: str) -> None:
        self._log('INFO', msg)

    def warn(self, msg: str) -> None:
        self._log('WARN', msg)

    def error(self, msg: str) -> None:
        self._log('ERROR', msg)

    def _log(self, level: str, msg: str) -> None:
        text = (msg or '')[:2000]
        stamp = datetime.now().strftime('%H:%M:%S')
        line = f'{stamp} {level} {text}'
        if self.stdout is not None:
            self.stdout.write(line + '\n')
            if hasattr(self.stdout, 'flush'):
                self.stdout.flush()
        self._buffer.append(
            FolderScanLog(run=self.run, level=level, message=text)
        )
        self.flush()

    def flush(self, force: bool = False) -> None:
        """Persist buffered logs and run heartbeat when thresholds are met."""
        if not self._buffer and not force:
            return
        elapsed = time.monotonic() - self._last_flush
        if not force and len(self._buffer) < 50 and elapsed < 2:
            return

        if self._buffer:
            FolderScanLog.objects.bulk_create(self._buffer)
            self._buffer = []

        update_fields = self._run_update_fields()
        FolderScanRun.objects.filter(pk=self.run.pk).update(**update_fields)
        self._last_flush = time.monotonic()

    def _run_update_fields(self) -> dict[str, Any]:
        return {
            'folders_saved': self.run.folders_saved,
            'graph_calls': self.run.graph_calls,
            'graph_retries': self.run.graph_retries,
            'contract_folders': self.run.contract_folders,
            'delivery_order_folders': self.run.delivery_order_folders,
            'other_folders': self.run.other_folders,
            'matched_expected': self.run.matched_expected,
            'matched_elsewhere': self.run.matched_elsewhere,
            'matched_no_db_path': self.run.matched_no_db_path,
            'matched_idiq': self.run.matched_idiq,
            'no_contract_in_db': self.run.no_contract_in_db,
            'duplicate_folders': self.run.duplicate_folders,
            'contracts_without_folder': self.run.contracts_without_folder,
            'do_parent_mismatch': self.run.do_parent_mismatch,
            'drive_ids_written': self.run.drive_ids_written,
            'paths_fixed': self.run.paths_fixed,
            'current_path': self.run.current_path or '',
            'heartbeat_at': timezone.now(),
        }
