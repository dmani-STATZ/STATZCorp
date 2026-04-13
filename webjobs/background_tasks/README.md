# Background Tasks WebJob

Runs `python manage.py run_background_tasks`, which executes registered tasks in sequence (currently `send_queued_rfqs` for Graph dispatch of `READY_TO_SEND` RFQs).

## Schedule (NCrontab)

The `settings.job` value `0 */15 11-22 * * *` uses **NCrontab six-field** cron (seconds first):

- Every **15 minutes** between **11:00 UTC** and **22:00 UTC** inclusive.
- **11:00–22:00 UTC** corresponds to **6:00 AM–5:00 PM Central Standard Time (UTC−6)**.
- During **CDT (UTC−5)** the same UTC window is **6:00 AM–5:00 PM local**; no schedule change is required.
- The window is intentionally offset from the DIBBS import WebJob (**6:00 AM UTC**) and the awards scraping WebJob (**7:00 AM UTC**).

## Azure deployment

Zip `run.sh` and `settings.job` per your existing WebJob process (see other `webjobs/*/README.md` files in this repo).
