# run_auto_import_dibbs WebJob

Reconciles DIBBS available dates against ImportBatch records.
Fetches and imports any missing or errored dates using fetch_dibbs_archive_files()
and run_import() — the same services used by the manual import flow.

## Schedule
Triggered WebJob — runs once daily at 2:00 AM CT.
CRON expression: `0 0 7 * * *` (7:00 UTC = 2:00 AM CDT / 1:00 AM CST)

Note: awards scraper (scrape_awards) runs at 4:00 AM CT — this job runs first
to avoid contention on Playwright/Chromium.

## Azure Setup
1. In Azure Portal → App Service → WebJobs → Add:
   - Name: `run_auto_import_dibbs`
   - File upload: zip of this folder containing run.sh
   - Type: Triggered
   - Triggers: Scheduled
   - CRON expression: `0 0 7 * * *`

## Required Environment Variables
- GRAPH_MAIL_ENABLED, GRAPH_MAIL_TENANT_ID, GRAPH_MAIL_CLIENT_ID,
  GRAPH_MAIL_CLIENT_SECRET, GRAPH_MAIL_SENDER — same as awards/RFQ mail
- AWARDS_ALERT_EMAIL — failure alerts go to this address

## Failure behavior
On any fetch or import failure, a consolidated alert email is sent via
Graph mail to AWARDS_ALERT_EMAIL. The manual import button remains available
as a fallback for any dates that need re-import.