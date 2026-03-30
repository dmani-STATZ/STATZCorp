# run_fetch_pending_pdfs WebJob

**Status:** **Deprecated** as the default high-frequency scheduled job. Nightly
`auto_import_dibbs` now runs **Loop B** (set-aside PDF harvest, batches of 10
with a fresh Playwright session per batch) and **Loop C** (`parse_pdf_data_backlog`)
for procurement history and packaging.

This WebJob / command remains useful for **manual** runs or a **light** schedule
when you need to fetch PDFs for **RFQ-queue** solicitations (`PENDING` /
`FAILED`, `pdf_fetch_attempts < 5`, `pdf_data_pulled` null) that are not covered
by the nightly set-aside harvest.

## Behavior

- Fetches up to **10** pending sols per Playwright session (browser fully closed
  between batches).
- Saves `pdf_blob`, `pdf_fetched_at`, `pdf_fetch_status` on success; increments
  attempts and sets `FAILED` on failure; sets `pdf_data_pulled` on the **fifth**
  failure (no blob) to stop infinite retries.
- After **all** fetch batches complete, runs **`parse_pdf_data_backlog()`** so
  parsing happens with **no** ORM inside `sync_playwright()`.

## Schedule (if still deployed)

If you keep this WebJob, use a low-frequency CRON or on-demand trigger only —
not every five minutes.

## Azure Setup

1. Deploy the app so this folder is present at:
   `/home/site/wwwroot/webjobs/run_fetch_pending_pdfs/`
2. In Azure Portal → App Service → WebJobs → Add:
   - Name: `run_fetch_pending_pdfs`
   - File upload: zip of this folder containing `run.sh`
   - Type: Triggered
   - Triggers: Scheduled (optional / infrequent)

## Dependencies

Requires Playwright + Chromium on the App Service instance (same as
`scrape_awards` and `auto_import_dibbs`).
