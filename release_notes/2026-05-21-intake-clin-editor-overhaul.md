---
id: 2026-05-21-intake-clin-editor-overhaul
title: Intake — CLIN editor overhaul with GP Split
published: true
publish_date: 2026-05-21
tags: [improved, contracts]
critical: false
---

The intake draft editor CLIN section has been fully redesigned.

**What changed:**

- CLIN rows are now **expandable cards** with clearly separated **Contract Data** and **Supplier/Quote** sections (replaces the wide flat table).
- **Item Type**, **IA**, and **FOB** fields now show full labels (Production, GFAT, Origin, Destination, etc.) instead of single-letter codes.
- **Supplier Due Date** and **Special Payment Terms** dropdown added to each CLIN.
- Finance lines are now entered **per-CLIN** — the shared root-level Finance Lines table has been removed from the editor.
- Each CLIN has a new **GP Split** section: enter company name + percentage; split dollar value is calculated automatically from planned GP.
- New **GP Summary** block shows per-CLIN planned GP, packaging deduction, and net contract GP — calculated live as you type.
- **Quote Total** auto-calculates as `unit price × order qty` per CLIN.
- CLIN Item Type now defaults to Production when not specified by the parser.
- Packaging section is now hidden by default — click **Add Packaging** to open it.
- CLIN cards now start collapsed; expand individually as needed.

**Also fixed:**
- Parsed 1155 unit price now correctly populates Item Value (government contract price), not Quote Price.
- CLIN IA (Inspection/Acceptance) field now correctly mapped from the 1155 parser result.
- Contract-level due date now derived at ingest as the earliest CLIN due date.
- Sales Class now defaults to STATZ on PDF ingest when that SalesClass record exists.
- GP calculation corrected: item value is now multiplied by order qty before subtracting the supplier quote total.
