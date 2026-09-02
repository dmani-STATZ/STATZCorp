# Contract Log Export WebJob

Runs `python manage.py process_contract_log_exports`, which claims and generates the oldest queued `ContractLogExportJob` (created when a user clicks Export on the Contract Log page), writes the XLSX to `MEDIA_ROOT/exports/contract_log/<job_id>.xlsx`, and notifies the requesting user via `SystemMessage` when it's ready (or failed).

This is a **separate, dedicated WebJob** — deliberately not registered in `TASK_FUNCTIONS`/`ScheduledTask` alongside `run_background_tasks`. That heartbeat runs its tasks sequentially in one process; a Contract Log export (potentially tens of thousands of rows) must not be able to block RFQ sending, mailer dispatch, or calendar sync for however long it takes to generate.

> **Deployment:** After any change to `settings.job`, the WebJob must be re-zipped and re-deployed via the Kudu API. The new cron schedule does not take effect until the WebJob is re-registered.

## Schedule (NCrontab)

`settings.job` uses `0 * 11-22 * * *` — the same window as `webjobs/background_tasks`:

- Every **1 minute** between **11:00 UTC** and **22:00 UTC** (6:00 AM–5:00 PM Central).
- A user who clicks Export sees their job picked up within ~1 minute worst case.

## Behavior

Each invocation:
1. Sweeps any job stuck in `RUNNING` for more than 20 minutes and marks it `FAILED` (crash/timeout recovery).
2. Claims and generates at most one `PENDING` job (oldest first), via an atomic conditional `UPDATE` so two overlapping invocations can't double-process the same job.
3. Prunes `DONE`/`FAILED` jobs (and their files) older than 7 days — there's no other retention mechanism for these generated files.

If no job is pending, the run is a no-op (single cheap query).

## Azure deployment

Zip `run.sh` and `settings.job` per the existing WebJob process (see other `webjobs/*/README.md` files in this repo). Re-deploy the zip via the Kudu API whenever `settings.job` changes so the new schedule is registered.
