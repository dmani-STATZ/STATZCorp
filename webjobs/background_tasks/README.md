# Background Tasks WebJob

Runs `python manage.py run_background_tasks`, which executes registered tasks in sequence, each isolated in a `try/except` so one failure cannot prevent subsequent tasks from running.

## Schedule (NCrontab)

The `settings.job` value `0 */15 11-22 * * *` uses **NCrontab six-field** cron (seconds first):

- Every **15 minutes** between **11:00 UTC** and **22:00 UTC** inclusive.
- **11:00–22:00 UTC** corresponds to **6:00 AM–5:00 PM Central Standard Time (UTC−6)**.
- During **CDT (UTC−5)** the same UTC window is **6:00 AM–5:00 PM local**; no schedule change is required.
- The window is intentionally offset from the DIBBS import WebJob (**6:00 AM UTC**) and the awards scraping WebJob (**7:00 AM UTC**).

## Tasks

Tasks run in order; a failure in one does **not** abort the others.

| # | Name | Module | Description |
|---|------|--------|-------------|
| 1 | `send_queued_rfqs` | `sales/tasks/send_queued_rfqs.py` | Sends grouped RFQ emails via Microsoft Graph for all `SupplierRFQ` rows in `READY_TO_SEND` state. |
| 2 | `poll_we_won_today` | `sales/tasks/poll_we_won_today.py` | Queries DIBBS AwdRecs.aspx per active CompanyCAGE (plain requests, no Playwright) for today's awards and feeds results into the same import + we-won pipeline used by the nightly scraper. Guarded by `WE_WON_POLL_ENABLED`. |
| 3 | `sync_sharepoint_calendar` | `users/tasks/sync_calendar.py` | Syncs portal calendar events to SharePoint. |

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `GRAPH_MAIL_ENABLED` | Set to `"true"` to enable Graph email dispatch for `send_queued_rfqs`. |
| `GRAPH_MAIL_SENDER_RFQ` | Sender address used by `send_queued_rfqs` (e.g. `quotes@statzcorp.com`). |
| `WE_WON_POLL_ENABLED` | Set to `"true"` to enable the daytime we-won CAGE poll. Omit or set to any other value to disable without a deploy. |

## Azure deployment

Zip `run.sh` and `settings.job` per your existing WebJob process (see other `webjobs/*/README.md` files in this repo).
