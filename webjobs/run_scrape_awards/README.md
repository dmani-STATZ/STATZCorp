# DIBBS Awards Scraper WebJob

## What This Does
Runs the Django management command `scrape_awards`, which scrapes DIBBS award
records into the `DibbsAward` table (nightly reconciliation by default).

As the **final in-process phase** of that command (not a separate shell step),
`scrape_awards` also runs Competitor Supplier Intelligence entity extraction
for watched-competitor awards that still need parsing. That phase is
fault-isolated inside Python — a failure there is logged and never causes the
WebJob to exit non-zero on its own. Tunables (optional App Service env vars):

- `COMPETITOR_ENTITY_BATCH_SIZE` (default `50`)
- `COMPETITOR_ENTITY_MAX_DURATION_SECONDS` (default `1800`)

## Azure Deployment Instructions
1. Zip ONLY the `run.sh` file (not the folder, just the file):
   - On Windows: right-click run.sh → Send to → Compressed folder
   - On Mac/Linux: `zip run.sh.zip run.sh`
2. In Azure Portal → STATZWeb → WebJobs → Add
3. Name: scrape-dibbs-awards
4. File Upload: upload the zip file
5. Type: Triggered
6. Triggers (CRON): 0 0 9 * * *   ← runs at 9:00 AM UTC daily
   (Adjust UTC offset for your timezone — 9 AM UTC = 4 AM Eastern / 3 AM Central)
7. Click OK

## Manual Run
SSH into App Service and run:
  python manage.py scrape_awards
  python manage.py scrape_awards --date 2026-03-25

## Logs (Azure WebJob)
The WebJob captures **stdout and stderr** from this script. The management command prints timestamped `[scrape_awards]` lines for each phase (inventory, DB sync, scrape queue, per-date browser steps, competitor entity extraction, notifications).

In Azure Portal: **App Service → WebJobs → (your job) → Logs** (or **Log stream** while the job runs).
