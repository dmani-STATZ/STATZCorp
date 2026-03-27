# run_fetch_pending_pdfs WebJob

Fetches pending DIBBS solicitation PDFs for all solicitations where
`pdf_fetch_status = PENDING` and `pdf_fetch_attempts < 5`.

Opens a single shared Playwright browser session, fetches all pending PDFs,
saves blobs to `Solicitation.pdf_blob`, and runs procurement history parsing
into `dibbs_nsn_procurement_history`.


## Schedule

Triggered WebJob — runs every 5 minutes during office hours.
CRON schedule configured in Azure portal: `0 */5 10-20 * * *`
(Every 5 minutes, 7am–7pm UTC — adjust to match CT office hours if needed)


## Azure Setup

1. Deploy the app so this folder is present at:
&#x20;  `/home/site/wwwroot/webjobs/run_fetch_pending_pdfs/`
2. In Azure Portal → App Service → WebJobs → Add:
&#x20;  - Name: `run_fetch_pending_pdfs`
&#x20;  - File upload: zip of this folder containing `run.sh`
&#x20;  - Type: Triggered
&#x20;  - Triggers: Scheduled
&#x20;  - CRON expression: `0 */5 7-19 * * *`



## Retry behavior

Sols that fail fetch have `pdf_fetch_attempts` incremented.
After 5 failed attempts the sol is permanently skipped until
`pdf_fetch_attempts` is manually reset to 0 by staff.



## Dependencies

Requires Playwright + Chromium installed on the App Service instance.
Same Playwright dependency as `scrape_awards` and the manual PDF fetch.

