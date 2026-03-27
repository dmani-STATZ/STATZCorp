# DIBBS Awards Scraper WebJob

## What This Does
Runs the Django management command `scrape_awards` which scrapes today's
DIBBS award records directly into the DibbsAward table.
Scraper defaults to running the day prior to the current day.

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
The WebJob captures **stdout and stderr** from this script. The management command prints timestamped `[scrape_awards]` lines for each phase (inventory, DB sync, scrape queue, per-date browser steps, notifications). `run.sh` sets `PYTHONUNBUFFERED=1` and uses `python -u` so lines appear in the portal **Log stream** as they are written instead of only when the buffer fills.

In Azure Portal: **App Service → WebJobs → (your job) → Logs** (or **Log stream** while the job runs).
