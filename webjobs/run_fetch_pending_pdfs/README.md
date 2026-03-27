\# run\_fetch\_pending\_pdfs WebJob



Fetches pending DIBBS solicitation PDFs for all solicitations where

`pdf\_fetch\_status = PENDING` and `pdf\_fetch\_attempts < 5`.



Opens a single shared Playwright browser session, fetches all pending PDFs,

saves blobs to `Solicitation.pdf\_blob`, and runs procurement history parsing

into `dibbs\_nsn\_procurement\_history`.



\## Schedule

Triggered WebJob — runs every 5 minutes during office hours.

CRON schedule configured in Azure portal: `0 \*/5 10-20 \* \* \*`

(Every 5 minutes, 7am–7pm UTC — adjust to match CT office hours if needed)



\## Azure Setup

1\. Deploy the app so this folder is present at:

&#x20;  `/home/site/wwwroot/webjobs/run\_fetch\_pending\_pdfs/`

2\. In Azure Portal → App Service → WebJobs → Add:

&#x20;  - Name: `run\_fetch\_pending\_pdfs`

&#x20;  - File upload: zip of this folder containing `run.sh`

&#x20;  - Type: Triggered

&#x20;  - Triggers: Scheduled

&#x20;  - CRON expression: `0 \*/5 7-19 \* \* \*`



\## Retry behavior

Sols that fail fetch have `pdf\_fetch\_attempts` incremented.

After 5 failed attempts the sol is permanently skipped until

`pdf\_fetch\_attempts` is manually reset to 0 by staff.



\## Dependencies

Requires Playwright + Chromium installed on the App Service instance.

Same Playwright dependency as `scrape\_awards` and the manual PDF fetch.

