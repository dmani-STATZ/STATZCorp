"""Exceptions raised by the folder scan package."""

from __future__ import annotations

from datetime import datetime
from typing import Optional


class GraphScanError(Exception):
    """Graph API failure during a folder scan."""


class ScanAlreadyRunning(Exception):
    """Another non-stale scan is already running for this root path."""

    def __init__(self, run_id: int, heartbeat_at: Optional[datetime]):
        self.run_id = run_id
        self.heartbeat_at = heartbeat_at
        super().__init__(f'Scan run {run_id} is already running.')


class NoCompletedScan(Exception):
    """No completed scan exists for the requested root path."""
