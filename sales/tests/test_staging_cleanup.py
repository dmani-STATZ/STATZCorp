from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from sales.models import (
    AwardImportBatch,
    DibbsAwardStaging,
    DibbsAwardStagingError,
)
from sales.services.staging_cleanup import purge_orphaned_staging


class PurgeOrphanedStagingTests(TestCase):
    def _batch(self, status, last_attempted_at):
        return AwardImportBatch.objects.create(
            award_date=timezone.localdate(),
            filename=f"{status}.html",
            source=AwardImportBatch.SOURCE_AUTO_SCRAPE,
            scrape_status=status,
            last_attempted_at=last_attempted_at,
        )

    def _staging_row(self, batch, suffix):
        stage_id = f"stage-{suffix}"
        row = DibbsAwardStaging.objects.create(
            stage_id=stage_id,
            batch=batch,
            notice_id=f"notice-{suffix}",
            award_basic_number=f"award-{suffix}",
        )
        DibbsAwardStagingError.objects.create(
            stage_id=stage_id,
            batch=batch,
            staged_at=timezone.now(),
            raw_award_basic_number=row.award_basic_number,
            error_reason="test",
        )
        return row

    def test_purges_only_stale_failed_and_in_progress_batches(self):
        now = timezone.now()
        stale_in_progress = self._batch(
            AwardImportBatch.SCRAPE_IN_PROGRESS, now - timedelta(hours=25)
        )
        stale_failed = self._batch(
            AwardImportBatch.SCRAPE_FAILED, now - timedelta(days=2)
        )
        recent_failed = self._batch(
            AwardImportBatch.SCRAPE_FAILED, now - timedelta(hours=2)
        )
        stale_success = self._batch(
            AwardImportBatch.SCRAPE_SUCCESS, now - timedelta(days=2)
        )
        stale_pending = self._batch(
            AwardImportBatch.SCRAPE_PENDING, now - timedelta(days=2)
        )

        purged_rows = [
            self._staging_row(stale_in_progress, "stale-progress"),
            self._staging_row(stale_failed, "stale-failed"),
        ]
        retained_rows = [
            self._staging_row(recent_failed, "recent-failed"),
            self._staging_row(stale_success, "stale-success"),
            self._staging_row(stale_pending, "stale-pending"),
        ]

        result = purge_orphaned_staging(older_than_hours=24)

        self.assertIsNone(result["error"])
        self.assertEqual(result["staging_rows"], 2)
        self.assertEqual(result["error_rows"], 2)
        self.assertEqual(
            {batch["batch_id"] for batch in result["batches"]},
            {stale_in_progress.id, stale_failed.id},
        )
        self.assertFalse(
            DibbsAwardStaging.objects.filter(
                id__in=[row.id for row in purged_rows]
            ).exists()
        )
        self.assertFalse(
            DibbsAwardStagingError.objects.filter(
                stage_id__in=[row.stage_id for row in purged_rows]
            ).exists()
        )
        self.assertEqual(
            set(
                DibbsAwardStaging.objects.filter(
                    id__in=[row.id for row in retained_rows]
                ).values_list("id", flat=True)
            ),
            {row.id for row in retained_rows},
        )
        self.assertEqual(
            DibbsAwardStagingError.objects.filter(
                stage_id__in=[row.stage_id for row in retained_rows]
            ).count(),
            3,
        )

    def test_dry_run_reports_without_deleting(self):
        stale_failed = self._batch(
            AwardImportBatch.SCRAPE_FAILED,
            timezone.now() - timedelta(days=2),
        )
        row = self._staging_row(stale_failed, "dry-run")

        result = purge_orphaned_staging(older_than_hours=24, dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["staging_rows"], 1)
        self.assertTrue(DibbsAwardStaging.objects.filter(id=row.id).exists())
        self.assertTrue(
            DibbsAwardStagingError.objects.filter(stage_id=row.stage_id).exists()
        )
