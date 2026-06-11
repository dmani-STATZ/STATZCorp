# Background Tasks WebJob

Runs `python manage.py run_background_tasks`, which checks the `ScheduledTask` registry on every heartbeat and executes only the tasks whose `interval_minutes` have elapsed. Each task is isolated in a `try/except` so one failure cannot prevent subsequent due tasks from running.

> **Deployment:** After any change to `settings.job`, the WebJob must be re-zipped and re-deployed via the Kudu API. The new cron schedule does not take effect until the WebJob is re-registered.

## Schedule (NCrontab)

The `settings.job` value `0 * 11-22 * * *` uses **NCrontab six-field** cron (seconds first):

- Every **1 minute** between **11:00 UTC** and **22:00 UTC** inclusive.
- **11:00–22:00 UTC** corresponds to **6:00 AM–5:00 PM Central Standard Time (UTC−6)**.
- During **CDT (UTC−5)** the same UTC window is **6:00 AM–5:00 PM local**; no schedule change is required.
- The window is intentionally offset from the DIBBS import WebJob (**6:00 AM UTC**) and the awards scraping WebJob (**7:00 AM UTC**).

The heartbeat fires every minute, but each task runs only when its own `interval_minutes` has elapsed since `last_run_at`. Intervals are stored in the `ScheduledTask` model (`core.ScheduledTask`).

## Tasks

Tasks run in `run_order` when multiple are due on the same heartbeat. A failure in one does **not** abort the others.

| # | Name | Interval | Module | Description |
|---|------|----------|--------|-------------|
| 1 | `send_queued_rfqs` | 5 min | `sales/tasks/send_queued_rfqs.py` | Sends grouped RFQ emails via Microsoft Graph for all `SupplierRFQ` rows in `READY_TO_SEND` state. |
| 2 | `poll_we_won_today` | 15 min | `sales/tasks/poll_we_won_today.py` | Queries DIBBS AwdRecs.aspx per active CompanyCAGE (plain requests, no Playwright) for today's awards and feeds results into the same import + we-won pipeline used by the nightly scraper. Guarded by `WE_WON_POLL_ENABLED`. |
| 3 | `sync_sharepoint_calendar` | 60 min | `users/tasks/sync_calendar.py` | Syncs portal calendar events to SharePoint. |
| 4 | `dispatch_campaigns` | 10 min | `mailer/tasks/dispatch_campaigns.py` | Dispatches outbound mailer campaigns. |
| 5 | `process_ai_snippets` | 5 min | `mailer/tasks/generate_ai.py` | Generates AI snippets for pending mailer content. |
| 6 | `dispatch_followups` | 10 min | `mailer/tasks/dispatch_followups.py` | Dispatches mailer follow-up messages. |

## Adding a New Task

1. Add a callable under the owning app's `tasks/` package.
2. Register the function in `TASK_FUNCTIONS` inside `core/management/commands/run_background_tasks.py`.
3. Insert a `ScheduledTask` row (via data migration or Django admin) with `name`, `interval_minutes`, and `run_order`.

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `GRAPH_MAIL_ENABLED` | Set to `"true"` to enable Graph email dispatch for `send_queued_rfqs`. |
| `GRAPH_MAIL_SENDER_RFQ` | Sender address used by `send_queued_rfqs` (e.g. `quotes@statzcorp.com`). |
| `WE_WON_POLL_ENABLED` | Set to `"true"` to enable the daytime we-won CAGE poll. Omit or set to any other value to disable without a deploy. |

## Azure deployment

Zip `run.sh` and `settings.job` per your existing WebJob process (see other `webjobs/*/README.md` files in this repo). **Re-deploy the zip via the Kudu API** whenever `settings.job` changes so the new schedule is registered.
