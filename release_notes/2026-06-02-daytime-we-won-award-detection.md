---
id: 2026-06-02-daytime-we-won-award-detection
title: Daytime We-Won Award Detection
published: true
publish_date: 2026-06-02
tags: [new, contracts]
critical: false
---

### Feature: Daytime We-Won Award Detection

Analysts and Barbara will now see we-won awards appear in the **Intake Queue** during business hours—typically within 15 minutes of DIBBS posting them—rather than waiting for the next morning's nightly run.

#### What Changed
A new background task (`poll_we_won_today`) has been added to poll DIBBS every 15 minutes during business hours (approximately 6:00 AM to 5:00 PM CT, Monday through Friday) specifically for awards posted to our company CAGE codes. When a daytime award is detected, it is immediately added to the Process Queue, and a corresponding skeleton draft is created in the Intake Queue automatically, matching the nightly ingestion behavior.

#### How It Works for Users
No manual action is required. Awards won during the day will automatically populate the Intake Queue in near real-time (within ~15 minutes of being posted on DIBBS), accelerating the intake and contract processing workflows.

#### Admin & System Note
- This feature is controlled by the `WE_WON_POLL_ENABLED` environment variable, which must be set to `true` to enable execution.
- The full nightly scrape (`scrape_awards`) remains unchanged as the final daily backstop. 
- Any awards successfully processed during the day by the 15-minute poller are automatically deduped (by award number) and skipped during the nightly run.
