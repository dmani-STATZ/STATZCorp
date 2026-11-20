---
id: 2026-11-20-quote-settings-and-rfq-test-mode
title: Quotes Settings and RFQ Test Mode
published: false
publish_date: 2026-11-20
tags: [new, sales]
critical: false
---

Superusers now have a **Settings** page in Quotes, linked from the Quotes menu.

**RFQ Test Mode** sends every supplier email the Quotes app produces — RFQ Queue sends and packhouse quote requests — to one test address you choose, instead of the supplier. The subject starts with `[TEST]`, and the message lists who would have received it. Suppliers receive nothing, the RFQ stays in the queue, and no packhouse request is recorded, so you can try again. Test Mode will not turn on without a valid address, and it will not accept a supplier's or a contact's address. While it is on, a warning shows at the top of every Quotes page.

The **Email scanning** switch on that page is visible but not usable yet.

The page also shows a read-only status card: whether TypeSafe is on, whether its API key is set (never the key itself), the AI budget balance, and when the background tasks last ran.
