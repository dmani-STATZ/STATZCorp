---
id: 2026-11-20-quote-email-scanning
title: Supplier email scanning in the Quotes mailbox
published: false
publish_date: 2026-11-20
tags: [new, sales]
critical: false
---

Incoming supplier mail can be checked automatically when a superuser turns on **Email scanning** under **Quotes → Settings**. The system classifies messages, blocks known bad senders, and—when a message looks like a quote—reads attachments in the background so you can log the numbers faster.

## Inbox badges

After mail is processed you may see:

- **Quote ready** — extraction finished; open **Log supplier quote** (link the SOL first if needed).
- **Scanning** — a background scan is running.
- **Quote · set supplier** — looks like a quote but we need the supplier on the message.
- **Possible blocked** — may involve a blocked company; review or use **Scan anyway** in the message.
- **Blocked** — sender is on the blocklist.
- **Scan failed** — automatic or manual scan failed; try **Scan quote**.

Use the **Quote ready** and **Held** filters on the mailbox list to focus the queue. Badges update when you load or sync the inbox, not live while you sit on the page.

## Scan quote (manual)

**Scan quote** queues one Sonnet read of the open message (body + PDF/image attachments). The button shows **Scanning…** while the worker runs; when it finishes you get a field count and can open the tray for prefilled values. **Always review before saving**—the scan never writes a quote by itself.

Scans run during worker hours (about 5 AM–5 PM Central). After hours, the status line explains that the scan waits until morning.

## Block sender

**More → Block sender…** on a message blocks that sender (reason required). Any Quotes user can block from the mailbox. You cannot block a whole public domain such as gmail.com—block the specific address instead.

Superusers manage all blocks under **Settings → Blocked senders** (add, list, **Unblock**). Unblocking allows new mail to be scanned again; older messages already marked blocked may need **Scan quote** once after unblock.