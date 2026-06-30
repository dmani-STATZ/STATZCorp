---
id: 2026-06-30-rfq-sales-contact-dispatch
title: RFQ Emails Now Use Sales Contact Category
published: false
publish_date: 2026-06-30
tags: [improved, sales]
critical: false
---

Outbound RFQ emails now target supplier contacts tagged with the **Sales** category instead of the standalone RFQ Email field.

- **Dispatch:** All Sales-category contact emails receive grouped RFQ sends (deduped). If none exist, the system falls back to the legacy RFQ Email value when present.
- **Data migration:** Existing RFQ Email values were converted to Sales-tagged contacts automatically on deploy.
- **Deprecated field:** The RFQ Email field on the supplier record is no longer editable in forms; assign the Sales category on a contact instead.
- **Supplier detail UI:** The standalone RFQ Email section was removed from the supplier detail page; Sales category pills on contact cards indicate RFQ recipients.
