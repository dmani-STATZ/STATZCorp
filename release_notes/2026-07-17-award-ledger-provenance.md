---
id: 2026-07-17-award-ledger-provenance
title: Enhanced Award Ledger tracking with manual draft creation, user provenance, and ingestion sources
published: true
publish_date: 2026-07-17
tags: [new, sales]
critical: false
---

The **Award Ledger** has been upgraded to track all contracts regardless of source, providing complete visibility into how drafts enter and move through the intake system.

- **Ingestion Source Tracking**: The ledger now tracks whether a draft entered the system via automatic **DIBBS Scrape**, **DIBBS Poll**, **PDF Upload**, or **Manual Entry**. Legacy rows are backfilled as **Legacy**.
- **Provenance Tracking**: Every stage of the draft journey now records the user who performed the action:
  - **Imported By**: Tracks the user who uploaded the PDF or created the manual draft (or "System" for automated DIBBS runs).
  - **Worked By**: Latches the first analyst who locked/started working on the draft.
  - **Finalized By**: Records the analyst who finalized the draft into a live contract.
- **Manual Draft Creation**: Added a **New Draft** action button and modal to the Intake Queue. Analysts can now manually inject a draft into the queue by specifying the contract type, contract number, and company.
- **Improved UI & Filters**:
  - The ledger page now features an **Ingestion Source** filter.
  - A badge indicating the ingestion source is shown next to each contract number.
  - The timeline steps display the specific user who worked on or finalized the contract.
  - Non-DIBBS entries display "N/A" in the "We Won" column to reflect that they did not originate from the DIBBS awards table.
