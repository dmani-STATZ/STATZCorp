"""Safe cleanup for stale DIBBS award staging runs."""

import logging
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from sales.models import (
    AwardImportBatch,
    DibbsAwardStaging,
    DibbsAwardStagingError,
)

logger = logging.getLogger(__name__)

DELETE_CHUNK_SIZE = 500
STALE_STATUSES = (
    AwardImportBatch.SCRAPE_IN_PROGRESS,
    AwardImportBatch.SCRAPE_FAILED,
)


def _chunked(values, size=DELETE_CHUNK_SIZE):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def purge_orphaned_staging(older_than_hours=24, *, dry_run=False):
    """
    Purge staging rows belonging to stale failed/in-progress scrape batches.

    All reads are materialized before writes for SQL Server connections without
    MARS. Errors are reported in the result and logged, never raised.
    """
    result = {
        "dry_run": dry_run,
        "older_than_hours": older_than_hours,
        "batches": [],
        "staging_rows": 0,
        "error_rows": 0,
        "error": None,
    }

    try:
        hours = int(older_than_hours)
        if hours < 1:
            raise ValueError("older_than_hours must be at least 1")

        cutoff = timezone.now() - timedelta(hours=hours)
        stale_batches = list(
            AwardImportBatch.objects.filter(
                scrape_status__in=STALE_STATUSES,
                last_attempted_at__lt=cutoff,
            ).values("id", "scrape_status", "last_attempted_at")
        )
        batch_ids = [row["id"] for row in stale_batches]

        staging_queryset = DibbsAwardStaging.objects.filter(batch_id__in=batch_ids)
        staging_ids = list(staging_queryset.values_list("id", flat=True))
        staging_metadata = list(
            staging_queryset.values("stage_id", "batch_id")
        )
        stage_ids = list({row["stage_id"] for row in staging_metadata})

        error_ids = []
        for stage_id_chunk in _chunked(stage_ids):
            error_ids.extend(
                list(
                    DibbsAwardStagingError.objects.filter(
                        batch_id__in=batch_ids,
                        stage_id__in=stage_id_chunk,
                    ).values_list("id", flat=True)
                )
            )

        counts_by_batch = Counter(row["batch_id"] for row in staging_metadata)
        result["batches"] = [
            {
                "batch_id": batch["id"],
                "scrape_status": batch["scrape_status"],
                "last_attempted_at": batch["last_attempted_at"],
                "staging_rows": counts_by_batch.get(batch["id"], 0),
            }
            for batch in stale_batches
            if counts_by_batch.get(batch["id"], 0)
        ]
        result["staging_rows"] = len(staging_ids)
        result["error_rows"] = len(error_ids)

        action = "Would purge" if dry_run else "Purging"
        for batch in result["batches"]:
            logger.info(
                "%s stale award staging: batch_id=%s status=%s rows=%s",
                action,
                batch["batch_id"],
                batch["scrape_status"],
                batch["staging_rows"],
            )

        if dry_run or not staging_ids:
            return result

        with transaction.atomic():
            for error_id_chunk in _chunked(error_ids):
                DibbsAwardStagingError.objects.filter(
                    id__in=error_id_chunk
                ).delete()
            for staging_id_chunk in _chunked(staging_ids):
                DibbsAwardStaging.objects.filter(id__in=staging_id_chunk).delete()

        logger.info(
            "Purged stale award staging: batches=%s staging_rows=%s error_rows=%s",
            len(result["batches"]),
            result["staging_rows"],
            result["error_rows"],
        )
    except Exception as exc:
        result["error"] = str(exc)
        logger.exception("Failed to purge stale award staging; continuing")

    return result
