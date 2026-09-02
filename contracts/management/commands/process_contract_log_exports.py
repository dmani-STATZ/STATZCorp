import os
import traceback
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from contracts.models import ContractLogExportJob
from contracts.services.contract_log_export import generate_contract_log_xlsx
from users.models import SystemMessage

STALE_RUNNING_MINUTES = 20
RETENTION_DAYS = 7


class Command(BaseCommand):
    help = "Generates the next queued Contract Log export job. Invoked by the process_contract_log_exports WebJob every minute."

    def handle(self, *args, **options):
        self._sweep_stale_jobs()

        job = self._claim_next_job()
        if job is None:
            self.stdout.write("No pending Contract Log export jobs.")
        else:
            self._process_job(job)

        self._prune_old_jobs()

    def _sweep_stale_jobs(self):
        cutoff = timezone.now() - timedelta(minutes=STALE_RUNNING_MINUTES)
        stale = ContractLogExportJob.objects.filter(
            status=ContractLogExportJob.STATUS_RUNNING,
            started_at__lt=cutoff,
        )
        count = stale.update(
            status=ContractLogExportJob.STATUS_FAILED,
            completed_at=timezone.now(),
            error_message="Export timed out or the worker crashed mid-run.",
        )
        if count:
            self.stdout.write(f"Marked {count} stale running job(s) as failed.")

    def _claim_next_job(self):
        candidate = ContractLogExportJob.objects.filter(
            status=ContractLogExportJob.STATUS_PENDING
        ).order_by('requested_at').first()

        if candidate is None:
            return None

        claimed = ContractLogExportJob.objects.filter(
            pk=candidate.pk, status=ContractLogExportJob.STATUS_PENDING
        ).update(status=ContractLogExportJob.STATUS_RUNNING, started_at=timezone.now())

        if not claimed:
            # Another invocation claimed it first.
            return None

        candidate.refresh_from_db()
        return candidate

    def _process_job(self, job):
        self.stdout.write(f"[{timezone.now().isoformat()}] Generating export job {job.id} for company {job.company_id}")
        try:
            file_bytes, row_count = generate_contract_log_xlsx(job.company, job.filters_applied)

            export_dir = os.path.join(settings.MEDIA_ROOT, 'exports', 'contract_log')
            os.makedirs(export_dir, exist_ok=True)
            file_path = os.path.join(export_dir, f"{job.id}.xlsx")
            with open(file_path, 'wb') as f:
                f.write(file_bytes)

            job.status = ContractLogExportJob.STATUS_DONE
            job.completed_at = timezone.now()
            job.row_count = row_count
            job.file_path = file_path
            job.save(update_fields=['status', 'completed_at', 'row_count', 'file_path'])

            self._notify(job, success=True)
            self.stdout.write(f"[{timezone.now().isoformat()}] Job {job.id} done: {row_count} rows.")
        except Exception as exc:
            job.status = ContractLogExportJob.STATUS_FAILED
            job.completed_at = timezone.now()
            job.error_message = f"{exc}\n{traceback.format_exc()}"
            job.save(update_fields=['status', 'completed_at', 'error_message'])
            self._notify(job, success=False)
            self.stdout.write(f"[{timezone.now().isoformat()}] Job {job.id} failed: {exc}")

    def _notify(self, job, success):
        if not job.requested_by_id:
            return

        if success:
            action_url = reverse('contracts:download_contract_log_export', args=[job.id])
            SystemMessage.create_message(
                user=job.requested_by,
                title="Contract Log export ready",
                message=f"Your Contract Log export ({job.row_count} rows) is ready to download.",
                priority='medium',
                source_app='contracts',
                source_model='ContractLogExportJob',
                source_id=str(job.id),
                action_url=action_url,
            )
        else:
            SystemMessage.create_message(
                user=job.requested_by,
                title="Contract Log export failed",
                message="Your Contract Log export failed to generate. Please try again.",
                priority='high',
                source_app='contracts',
                source_model='ContractLogExportJob',
                source_id=str(job.id),
                action_url=reverse('contracts:contract_log_view'),
            )

    def _prune_old_jobs(self):
        cutoff = timezone.now() - timedelta(days=RETENTION_DAYS)
        old_jobs = ContractLogExportJob.objects.filter(
            status__in=[ContractLogExportJob.STATUS_DONE, ContractLogExportJob.STATUS_FAILED],
            requested_at__lt=cutoff,
        )
        count = 0
        for job in old_jobs:
            if job.file_path and os.path.exists(job.file_path):
                try:
                    os.remove(job.file_path)
                except OSError:
                    pass
            job.delete()
            count += 1
        if count:
            self.stdout.write(f"Pruned {count} old export job(s).")
