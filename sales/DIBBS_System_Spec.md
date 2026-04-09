# DIBBS Government Bidding System
## Technical Architecture & Design Specification
**Version 2.0  |  March 2026**
*Django + SQL Server  |  Procurement Pipeline Replacement*
*Updated March 11, 2026 — Sessions 5 & 6 complete. Phase 2 substantially done.*

---

## Table of Contents

- [📋 Project TODO — Implementation Checklist](#-project-todo--implementation-checklist)

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
   - 2.1 High-Level Architecture
   - 2.2 Core Data Flow
   - 2.3 DIBBS File Summary
   - 2.4 Infrastructure — Azure App Service
3. [Database Schema](#3-database-schema)
   - 3.1 Solicitation Tables
   - 3.2 Approved Source Table
   - 3.3 Supplier Tables
   - 3.4 Quoting & Bid Tables
4. [Supplier Matching Engine](#4-supplier-matching-engine)
   - 4.1 Matching Tiers
5. [BQ Batch Quote Export Engine](#5-bq-batch-quote-export-engine)
   - 5.0.1 Cursor Prompt — `bq_export.py`
   - 5.1 Field Mapping — Company-Filled Fields
   - 5.2 Export Process
6. [Django Application Structure](#6-django-application-structure)
   - 6.0 One App: `sales`
   - 6.1 `sales` App Internal Structure
   - 6.2 Relationship to Existing Apps
   - 6.3 Key Model Relationships
   - 6.4 Company Settings
7. [Phased Delivery Plan](#7-phased-delivery-plan)
8. [Resolved Decisions & Constraints](#8-resolved-decisions--constraints)
   - 8.1 Company CAGE Settings
   - 8.2 Markup / Pricing Logic
   - 8.3 RFQ Dispatch Workflow
9. [Application Flow & Page Tree](#9-application-flow--page-tree)
   - 9.1 Page Tree
   - 9.2 Navigation & Status Flow
   - 9.3 Design Vision & Visual Language
   - 9.4 Base Layout — Sidebar Shell
   - 9.5 Dashboard — `/sales/`
   - 9.6 Solicitations List — `/sales/solicitations/`
   - 9.7 Solicitation Detail — `/sales/solicitations/<sol#>/`
   - 9.8 Bid Builder — `/sales/bids/<sol#>/build/`
   - 9.9 Daily Import — `/sales/import/upload/`
10. [Email Workflow — Supplier Communication](#10-email-workflow--supplier-communication)
    - 10.1 The Core Problem
    - 10.2 Outbound RFQ Email Flow
    - 10.3 Inbound Response Reality Map
    - 10.4 The Quote Entry Form — Design Requirements
    - 10.5 RFQ Tracking — What the Sales Team Needs to See
    - 10.6 Database Additions for Email Tracking
    - 10.7 Email Template Spec
    - 10.8 RFQ Center UI Specification
    - 10.9 Solicitation-Level Communication View
11. [Email Workflow — Lookup & PDF Handling](#11-email-workflow--lookup--pdf-handling)
    - 11.1 The Email Lookup Problem
    - 11.2 Global Search — Specification
    - 11.3 RFQ Center Search — In-Queue Lookup
    - 11.4 PDF Files — Decision
    - 11.5 Summary of Decisions
12. [Sales Team Feedback — Demo Review](#12-sales-team-feedback--demo-review-mar-2026)
    - 12.1 Overall Reaction
    - 12.2 The Three-Bucket Triage Model (SDVOSB / HUBZone / Growth / Skip)
    - 12.3 Supplier Capability Data — Contracts Database
    - 12.3.1 Contract History Weighting
    - 12.4 Multiple CAGE Support
    - 12.5 RFQ Auto-Build Confirmation
    - 12.6 Dark Mode
    - 12.7 Timeline
13. [Session 7 — Remaining Work & Go-Live Checklist](#13-session-7--remaining-work--go-live-checklist)
    - 13.1 Go-Live Blockers
    - 13.2 Session 7 Recommended Build Tasks
    - 13.3 Complete Daily Workflow

---

## 📋 Project TODO — Implementation Checklist

Progress tracker for the DIBBS build. Each item links to the spec section with the detailed requirements.

### Phase 1 — Critical Path *(target: Weeks 1–2)* ✅ COMPLETE (including originally-deferred BQ items)

| Status | Task | Spec Section | Session |
|--------|------|-------------|---------|
| ✅ Done | Django `sales` app created, added to `INSTALLED_APPS` | §6.0 | S0 |
| ✅ Done | All `dibbs_*` database models defined and migrated | §3, §6.1 | S0 |
| ✅ Done | IN / BQ / AS file parser (`services/parser.py`) | §2, §5 | S1 |
| ✅ Done | Daily import view + file upload UI — 3-step wizard (`views/imports.py`) | §9.9 | S1 |
| ✅ Done | Solicitation browse & search UI with bucket tab strip (`views/solicitations.py`) | §9.6 | S1, S3 |
| ✅ Done | Solicitation detail page — Overview + Matches tabs, pipeline track | §9.7 | S3 |
| ✅ Done | Global search endpoint + topbar search UI with typeahead | §11.2 | S3 |
| ✅ Done | Basic bid status tracking (status field + pipeline steps UI) | §3.1 | S3 |
| ✅ Done | Dashboard — live counts, bucket breakdown, urgent alert | §9.5 | S3 |
| ✅ Done | `sales/urls.py` wired into project `urls.py` | §6.1 | S1 |
| ✅ Done | Solicitation triage buckets — `bucket` field + `assign_triage_bucket()` auto-assign on import | §12.2 | S1, S3 |
| ✅ Done | Triage UI — bucket filter tab strip on solicitation list (SDVOSB / HUBZone / Growth / Skip) | §12.2 | S3 |
| ✅ Done | No-bid action — POST endpoint, status update, redirect | §9.7 | S3 |
| ✅ Done | Manual BQ field entry form + bid builder (`views/bids.py`) | §9.8 | S5/S6 |
| ✅ Done | BQ export scaffold — all 121 columns (`services/bq_export.py`) | §5, §5.0.1 | S5 |

### Phase 2 — Core Automation *(target: Weeks 3–4)* ✅ SUBSTANTIALLY COMPLETE

| Status | Task | Spec Section | Session |
|--------|------|-------------|---------|
| ✅ Done | 3-tier supplier matching engine (`services/matching.py`) | §4, §12.3 | S2 |
| ✅ Superseded | ~~Contract history backfill~~ — replaced by SQL view `dibbs_supplier_nsn_scored` + unmanaged `SupplierNSNScored`; `dibbs_supplier_nsn` is manual/quote-driven rows only | §4.2, §12.3 | Apr 2026 |
| ✅ Removed | ~~Backfill trigger~~ (`suppliers/backfill-nsn/`) — deleted | §4.2 | Apr 2026 |
| ✅ Done | Match review UI on solicitation detail — Matches tab with tier badges | §9.7 | S3 |
| ⬜ Todo | HUBZone flag UI — bulk-mark solicitations as HUBZone from solicitation list | §12.2 | S7 |
| ✅ Done | RFQ email generation (`services/email.py`) — outbound + follow-up templates | §10.2, §10.7 | S4 |
| ✅ Done | RFQ dispatch — Pending queue + send batch/single (`views/rfq.py`) | §10.5, §10.8 | S4 |
| ✅ Done | RFQ Sent list — Overdue / Urgent / Awaiting / Responded / Closed sections | §10.8 | S4 |
| ✅ Done | 3-panel RFQ Center — fetch-driven, inline quote entry, live queue filter | §10.8 | S5/S6 |
| ✅ Done | Supplier quote entry form — Unit Price + Lead Time, live suggested bid, Ctrl+Enter | §10.4 | S4 |
| ✅ Done | Contact log — `SupplierContactLog` model + activity feed on solicitation detail | §10.6, §10.9 | S4 |
| ✅ Done | Follow-up email dispatch — `send_followup_email()`, follow_up_count tracking | §10.5, §10.7 | S4 |
| ✅ Done | `CompanyCAGE` model — `smtp_reply_to`, `default_markup_pct`, `is_default` | §8.1 | S4 |
| ✅ Done | `Solicitation.dibbs_pdf_url` — correct URL: `dibbs2.bsm.dla.mil/Downloads/RFQ/{subdir}/` | §11.4 | S4/S5 |
| ✅ Done | `bid_select_quote` — clears `is_selected_for_bid` on other quotes for same line before setting | §9.7 | S6 |
| ✅ Done | Solicitation detail — Matches tab Send RFQ wired; RFQs, Quotes, Activity tabs populated | §9.7 | S4 |
| ✅ Done | Bid assembly with margin calculation — `bid_builder`, `bids_ready`, `bid_select_quote` | §9.8 | S5/S6 |
| ✅ Done | BQ export service — 121-column overlay + validation (`services/bq_export.py`) | §5, §5.0.1 | S5 |
| ✅ Done | BQ export queue + download — `bids_export_queue`, `bids_export_download` | §5.2 | S5/S6 |
| ✅ Done | Supplier list + detail — Profile / Capabilities / Quote History tabs | §9.1 | S5/S6 |
| ✅ Done | Supplier NSN/FSC add & remove views | §6.1 | S5/S6 |
| ✅ Done | Import performance rewrite — bulk fetch/diff/bulk_create (~12 queries vs ~10,000) | §2.2 | S5 |
| ⏩ Deferred | Price history per NSN (trending charts) | §7 Phase 3 | Phase 3 |

### Phase 3 — Polish & Reporting *(target: post go-live)*

| Status | Task | Spec Section |
|--------|------|-------------|
| ⬜ Todo | HUBZone flag UI — bulk-mark from solicitation list (moved from Phase 2) | §12.2 |
| ⬜ Todo | Settings page — CompanyCAGE management UI (`/sales/settings/cages/`) | §8.1 |
| ⬜ Todo | Email settings — configure `EMAIL_*` in `settings.py` + default CompanyCAGE with `smtp_reply_to` | §10.2 |
| ⬜ Todo | BQ export full 121-column validation ruleset | §5 |
| ⬜ Todo | Bid History page — `/sales/bids/history/` all submitted bids with outcome tracking | §9.1 |
| ⬜ Todo | Import History page — `/sales/import/history/` all past import batches | §9.1 |
| ⬜ Todo | Win/loss reporting and analytics | §7 Phase 3 |
| ⬜ Todo | Price history per NSN — trending charts | §7 Phase 3 |
| ⬜ Todo | Bulk no-bid actions | §7 Phase 3 |
| ⬜ Todo | Role-based access control | §7 Phase 3 |
| ⬜ Todo | Dark mode | §12.6 |
| ⬜ Todo | User activity audit log — per-user report showing who triaged, queued, sent RFQs, entered quotes, and linked inbox messages. Data already partially captured via `sent_by`, `entered_by`, `logged_by`, `linked_by` fields. Missing: user FK on `bucket_assigned_by` (currently stores `'auto'`/`'manual'` string, not actual user). Full design TBD. | §13 Future |

### ⚠ Open Action Items

| Priority | Item | Owner | Section | Status |
|----------|------|-------|---------|--------|
| ✅ Resolved | `is_packhouse=True` on `contracts_supplier` identifies packaging facilities | Dev | §12.3 | Confirmed, implemented |
| ✅ Resolved | `award_date` is the field name on the Contract model | Dev | §12.3.1 | Confirmed, implemented |
| ✅ Resolved | Phase 1 complete before end of March 2026 | — | §12.7 | ✅ Complete |
| ✅ Resolved | `dibbs_pdf_url` using wrong domain/path | Dev | §11.4 | Fixed: uses `dibbs2.bsm.dla.mil/Downloads/RFQ/{subdir}/` |
| ✅ Resolved | `quote_select_for_bid` did not clear other quotes — `bid_select_quote` now clears first | Dev | §9.7 | Fixed in S6 |
| ✅ Resolved | Import timing out on large files (500 error) | Dev | §2.2 | Fixed: bulk rewrite in S5, ~12 queries total |
| ✅ Resolved | `Supplier.objects.filter(archived=False)` in `supplier_list` — `archived` field confirmed on `contracts_supplier` (`BooleanField(default=False)`) | Dev | §3.3 | Confirmed valid |
| 🟡 Med | Email settings not configured in `settings.py` — configure `EMAIL_*` + `DEFAULT_FROM_EMAIL` + create default `CompanyCAGE` record with `smtp_reply_to` before RFQ emails will send | Dev | §10.2 | Pending — required before go-live |
| 🟡 Med | Establish process for HUBZone partner to send solicitation lists + build bulk-flag UI | Sales/Dev | §12.2 | Pending — S7 |
| 🔴 High | `hubzone_requested_by` field missing from `Solicitation` model — must add + migrate before S7 HUBZone UI | Dev | §12.2 | S7 prerequisite — add `CharField(max_length=100, blank=True, default='')` to `dibbs_solicitation` |
| 🔴 S7 Prereq | `hubzone_requested_by` field missing from `Solicitation` model — add `CharField(max_length=100, blank=True, default="")` + run migration before S7 HUBZone UI | Dev | §12.2 | Needs migration |
| 🟡 Med | CompanyCAGE record must be created in Django admin before bid builder will work | Dev/Admin | §8.1 | Pending — required before go-live |

### Cursor Session Log

| Date | Session | Output |
|------|---------|--------|
| Mar 2026 | S0 — Models + initial migration | All `dibbs_*` models, migration file |
| Mar 2026 | S1 — Import pipeline + solicitation list | `parser.py`, `importer.py`, `views/imports.py`, `views/solicitations.py` (list), `urls.py`, `base.html`, `upload.html`, `list.html` |
| Mar 2026 | S2 — Matching engine + backfill | `services/matching.py` (3-tier engine); backfill path later replaced by live SQL view (Apr 2026) |
| Mar 2026 | S4 — RFQ dispatch, quote entry, email service | `services/email.py`, `models/cages.py` (CompanyCAGE), `models/rfq.py` (SupplierRFQ + SupplierContactLog), `views/rfq.py` (9 views), solicitation detail tabs, `rfq/pending.html`, `rfq/sent.html`, `rfq/quote_entry.html` |
| Mar 11, 2026 | S5 — BQ export, bid views, supplier views, import rewrite, RFQ Center + templates | `services/bq_export.py`, `services/importer.py` (perf rewrite), `views/bids.py` (stubs), `views/suppliers.py` (stubs), all templates: `rfq/center.html`, `rfq/partials/center_panel.html`, `bids/ready.html`, `bids/builder.html`, `bids/export_queue.html`, `suppliers/list.html`, `suppliers/detail.html`, `suppliers/add_nsn.html`, `suppliers/add_fsc.html` |
| Mar 11, 2026 | S6 — Missing view functions wired up | `views/rfq.py` (`rfq_center`, `rfq_center_detail`), `views/bids.py` (all 5 views complete), `views/suppliers.py` (all views complete), `views/__init__.py` updated |

---

## 1. Executive Summary

This document specifies the architecture, database schema, and implementation plan for a replacement government bidding system built on Django and Microsoft SQL Server. The system replicates and extends the functionality of an existing third-party platform that is being retired.

The system automates the full procurement pipeline for Defense Logistics Agency (DLA) DIBBS solicitations:

- Daily ingestion of DIBBS data files (IN, BQ, AS) into a structured SQL Server database
- Intelligent supplier matching by NSN, FSC/NIIN category, and approved source CAGE
- Automated supplier RFQ generation and delivery via email
- Quote collection, price tracking, and bid history per NSN
- Validated BQ batch quote file export for upload back to DIBBS

> ⚠ **Urgency:** The existing system is being retired. This replacement must reach a functional state within weeks. A phased delivery approach is defined in Section 7.

---

## 2. System Architecture

### 2.1 High-Level Architecture

The system follows a standard Django MVC architecture backed by SQL Server, deployed as a web application accessible to internal staff.

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Django Templates + Bootstrap 5 | UI for browsing solicitations, managing quotes, supplier data |
| Backend | Django 4.x (Python) | Business logic, file parsing, matching engine, email dispatch |
| Database | Microsoft SQL Server | Persistent storage for all solicitations, suppliers, bids |
| File I/O | Python (csv, fixed-width) | Parse IN/BQ/AS files; export completed BQ upload files |
| Email | Microsoft Graph API (`msal`) + `mailto:` fallback | Outbound RFQ dispatch from `quotes@statzcorp.com` (production) / `rfq@statzcorp.com` (dev/test); controlled by `GRAPH_MAIL_SENDER` env var; falls back to manual mailto when `GRAPH_MAIL_ENABLED=False` |
| Task Queue | Celery + Redis (optional) | Async daily file import and email sending |

### 2.2 Core Data Flow

The end-to-end pipeline moves through six stages:

```
[1] Download Files  →  [2] Import to DB  →  [3] Match Suppliers
      →  [4] Send RFQs  →  [5] Enter Supplier Pricing  →  [6] Export BQ & Submit to DIBBS
```

### 2.3 DIBBS File Summary

| File | Format | Contents | Rows (sample date) |
|------|--------|----------|-------------------|
| IN (Index) | Fixed-width TXT, 140 chars/row | All solicitations for the day: NSN, nomenclature, qty, return date, set-aside | 544 |
| BQ (Batch Quote) | CSV, 121 columns | Pre-filled quote shells — one row per solicitation line, ready for vendor data entry and upload | 578 |
| AS (Approved Source) | CSV, 4 columns | NSN → approved CAGE → part number mappings | 656 |

#### IN File Column Layout (fixed-width)

| Column Name | Length | Start | End |
|-------------|--------|-------|-----|
| Solicitation # | 13 | 0 | 12 |
| NSN/Part # | 46 | 13 | 58 |
| Purchase Request # | 13 | 59 | 71 |
| Return By Date | 8 | 72 | 79 |
| File Name | 19 | 80 | 98 |
| QTY | 7 | 99 | 105 |
| Unit Issue | 2 | 106 | 107 |
| Nomenclature | 21 | 108 | 128 |
| Buyer Code | 5 | 129 | 133 |
| AMSC | 1 | 134 | 134 |
| Item Type Indicator | 1 | 135 | 135 |
| Small Business Set-Aside | 1 | 136 | 136 |
| SB Set-Aside Percentage | 3 | 137 | 139 |

#### AS File Layout (CSV)

```
NSN, Approved Source CAGE, Part Number, Approved Source Company Name
"6640014392807","08071","XX63 1K1 15","MILLIPORE CORPORATION"
```

### 2.4 Infrastructure — Azure App Service

For high-performance deployments on **Azure App Service (Linux, Oryx build)**:

#### GCC High (Azure Government)

Production targets **Azure Government (GCC High)**. Identity and Microsoft Graph for mail/inbox use **US sovereign endpoints** (e.g. `login.microsoftonline.us`, `graph.microsoft.us`) — not commercial `.com` tenants. App Service, Key Vault, and CI/CD must be provisioned in the correct cloud; configuration and secrets are **not** interchangeable with commercial Azure.

#### Build vs runtime (Oryx)

- **`SCM_DO_BUILD_DURING_DEPLOYMENT=true`** must be set in the Azure Portal (**Configuration** → Application settings) so **Oryx runs the deployment build** (dependency restore, optional `collectstatic`, virtualenv layout under `/tmp` or the published `antenv`). If this is off or mis-set, the app can start without a complete Python environment and enter **crash loops** until the setting is corrected.
- **`collectstatic`** is produced during the **Oryx build** phase when static files are collected as part of deployment. Running `manage.py collectstatic` again in the **runtime** `startup.sh` is redundant, repeats heavy I/O, and can push container startup past health-check timeouts (~10+ minute boots). **Disable or omit collectstatic in the runtime startup script**; rely on the build output under `wwwroot`.
- **Runtime `startup.sh` must stay environment-aware:** the Oryx virtual environment path can change or be recreated across platform events. **Do not invoke bare `python`** for `manage.py`, Playwright, or Gunicorn wiring that depends on the app’s interpreter. The repo script resolves **`$PYTHON_EXE`** dynamically (discover `antenv` under `/tmp`, with a documented fallback), then uses `$PYTHON_EXE` for all Python entrypoints. Hard-coding `/tmp/antenv/bin/python` as the only path without discovery risks failures when the platform layout differs.

#### Playwright / Chromium at runtime

- **Playwright / Chromium** may still be needed at runtime for DIBBS fetch and PDF flows. Install or cache browser binaries during build when possible; if a runtime install remains, **gate** it on a filesystem check so restarts skip re-download when `.local-browsers` already exists (see repo `startup.sh`).

---

## 3. Database Schema

All tables use SQL Server. Django ORM models map directly to these tables. Identity columns serve as primary keys unless noted.

### 3.1 Solicitation Tables

#### `tbl_Solicitation` — one row per solicitation

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| SolicitationID | INT IDENTITY PK | — | Surrogate key |
| SolicitationNumber | VARCHAR(13) | IN col 1 / BQ col 1 | Unique, indexed. e.g. SPE1C126T0694 |
| SolicitationType | CHAR(1) | BQ col 2 | F=Fast Auto, I=AIDC, P=Auto Eval, blank |
| SmallBusinessSetAside | CHAR(1) | IN col 12 / BQ col 3 | N/Y/H/R/L/A/E |
| ReturnByDate | DATE | IN col 4 (MM/DD/YY) | Bid deadline |
| PDFFileName | VARCHAR(50) | IN col 5 | Links to downloaded PDF |
| BuyerCode | VARCHAR(5) | IN col 9 | DLA buyer identifier |
| ImportDate | DATE | System | Date the file was imported |
| ImportBatchID | INT FK | — | Links to tbl_ImportBatch |
| Status | VARCHAR(20) | App | See solicitation status table below (includes `New`, `Active`, pipeline states, `Archived`). |

**Solicitation `status` values (app field `Solicitation.status`):**

| Status | Meaning |
|--------|---------|
| `New` | Imported in today's batch — transitioned to Active on next import |
| `Active` | Prior import, untouched, within due date |
| `Matching` | Matching engine processing |
| `RFQ_PENDING` | Matched, awaiting RFQ dispatch |
| `RFQ_SENT` | RFQ emails sent to suppliers |
| `QUOTING` | At least one supplier quote received |
| `BID_READY` | Bid assembled and ready for export |
| `BID_SUBMITTED` | BQ file exported and submitted to DIBBS |
| `WON` | Award received |
| `LOST` | Award went elsewhere |
| `NO_BID` | Sales team elected not to bid |
| `Archived` | Past due date, terminal/untouched — hidden from default views |

**Lifecycle sweep (import):** At the start of each daily import (before a new `ImportBatch` is created), `_run_lifecycle_sweep()` in `sales/services/importer.py` runs inside a DB transaction: (1) `New` solicitations whose `ImportBatch.import_date` is before today become `Active`; (2) solicitations past `return_by_date` that are not in active pipeline statuses (`RFQ_PENDING` … `BID_SUBMITTED`), are **not** `NO_BID`, and are in `New`, `Active`, or `SKIP` bucket become `Archived`. **`NO_BID` is never auto-archived** — those rows stay visible on **Closed Solicitations** under the No-Bid tab. Counts are stored on the import parse step and shown on the import progress summary.

#### `tbl_SolicitationLine` — one row per NSN/line within a solicitation

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| LineID | INT IDENTITY PK | — | Surrogate key |
| SolicitationID | INT FK | — | → tbl_Solicitation |
| LineNumber | CHAR(4) | BQ col 44 | e.g. 0001 |
| PurchaseRequestNumber | VARCHAR(13) | BQ col 46 | |
| NSN | VARCHAR(46) | IN / BQ col 47 | Full NSN or part number. Indexed. |
| FSC | CHAR(4) | Derived | First 4 chars of NSN — used for FSC matching |
| NIIN | VARCHAR(9) | Derived | Chars 5–13 of NSN |
| UnitOfIssue | CHAR(2) | BQ col 48 | EA, LB, etc. |
| Quantity | INT | IN / BQ col 49 | Solicited quantity |
| DeliveryDays | INT | BQ col 51 | Required delivery days ADO |
| Nomenclature | VARCHAR(21) | IN col 8 | Item description |
| AMSC | CHAR(1) | IN col 10 | Acquisition Method Suffix Code |
| ItemTypeIndicator | CHAR(1) | IN col 11 | 1=NSN, 2=Part Number |
| ItemDescriptionIndicator | CHAR(1) | BQ col 105 | B/D/N/P/Q/S |
| TradeAgreementsIndicator | CHAR(1) | BQ col 62 | N/Y/I |
| BuyAmericanIndicator | CHAR(1) | BQ col 68 | N/Y/I |
| HigherLevelQualityIndicator | CHAR(1) | BQ col 117 | N/6/7/8 |

#### `tbl_ImportBatch` — tracks each daily file import

| Column | Type | Notes |
|--------|------|-------|
| ImportBatchID | INT IDENTITY PK | |
| ImportDate | DATE | Date of the DIBBS file (from filename: in260308 → 2026-03-08) |
| INFileName | VARCHAR(50) | |
| BQFileName | VARCHAR(50) | |
| ASFileName | VARCHAR(50) | |
| ImportedAt | DATETIME | When the import ran |
| SolicitationCount | INT | Number of records imported |
| ImportedBy | VARCHAR(50) | Django user who ran import |

---

### 3.2 Approved Source Table

#### `tbl_ApprovedSource` — from AS file

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| ApprovedSourceID | INT IDENTITY PK | — | |
| NSN | VARCHAR(46) | AS col 1 | Indexed |
| ApprovedCAGE | VARCHAR(5) | AS col 2 | Indexed |
| PartNumber | VARCHAR(50) | AS col 3 | |
| CompanyName | VARCHAR(100) | AS col 4 | |
| ImportBatchID | INT FK | — | → tbl_ImportBatch |

---

### 3.3 Supplier Tables

#### `contracts_supplier` — **EXISTING TABLE (do not recreate)**

> This table already exists in the project as the `Supplier` Django model in the `contracts` app. All new bidding tables reference it via FK. Do not modify its schema — only read from it.

Key fields relevant to the bidding system:

| Field (Django) | DB Column | Notes |
|----------------|-----------|-------|
| id | id | PK — used as FK target from all new tables |
| cage_code | cage_code | Primary lookup key for CAGE matching |
| name | name | Company name |
| business_email | business_email | Used for automated RFQ dispatch if contact email is absent |
| primary_email | primary_email | Preferred RFQ dispatch email |
| primary_phone | primary_phone | |
| contact | contact_id | FK → Contact — primary contact person for RFQ emails |
| probation | probation | If True, flag supplier in match results — do not auto-send RFQ |
| conditional | conditional | If True, flag in match results |
| archived | archived | If True, exclude entirely from matching engine |
| notes | notes | General supplier notes |

**RFQ email priority:** `contact.email` → `primary_email` → `business_email`

#### `dibbs_supplier_nsn` — explicit NSN-level supplier capability (manual + quote learning)

```python
class SupplierNSN(models.Model):
    supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.CASCADE,
                                  related_name='nsn_capabilities')
    nsn = models.CharField(max_length=46, db_index=True)  # normalized 13 digits, no hyphens
    notes = models.CharField(max_length=255, null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='nsn_capabilities_added')

    class Meta:
        db_table = 'dibbs_supplier_nsn'
        unique_together = ('supplier', 'nsn')
```

| Column | Type | Notes |
|--------|------|-------|
| id | INT IDENTITY PK | |
| supplier_id | INT FK | → contracts_supplier.id |
| nsn | VARCHAR(46) | NSN (normalized: 13 digits, no hyphens). Indexed. |
| notes | VARCHAR(255) NULL | |
| added_at | DATETIME | When the row was created |
| added_by_id | INT NULL FK | → auth_user (who added, if known) |

**Tier-1 match score** is **not** stored on this table. It is computed at read time by SQL Server view **`dibbs_supplier_nsn_scored`** (DDL in `sales/sql/dibbs_supplier_nsn_scored.sql`; deploy with `CREATE OR ALTER` in SSMS). Django reads it via unmanaged model **`SupplierNSNScored`** (`managed=False`, `db_table='dibbs_supplier_nsn_scored'`). Score = **1.0** base + sum of contract weights from `contracts_clin` / `contracts_contract` / `contracts_nsn` (1.0 if award ≤2y, 0.75 if ≤4y, 0.5 older).

#### `dibbs_supplier_fsc` *(new)* — FSC/category-level supplier capability

```python
class SupplierFSC(models.Model):
    supplier = models.ForeignKey('contracts.Supplier', on_delete=models.CASCADE,
                                  related_name='fsc_capabilities')
    fsc_code = models.CharField(max_length=4, db_index=True)
    notes = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'dibbs_supplier_fsc'
        unique_together = ('supplier', 'fsc_code')
```

| Column | Type | Notes |
|--------|------|-------|
| id | INT IDENTITY PK | |
| supplier_id | INT FK | → contracts_supplier.id |
| fsc_code | CHAR(4) | 4-digit Federal Supply Class. e.g. 8465 |
| notes | VARCHAR(255) NULL | |

---

### 3.4 Quoting & Bid Tables

#### `dibbs_supplier_rfq` *(new)* — RFQ sent to a supplier for a solicitation line

```python
class SupplierRFQ(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),   # created but email not yet sent
        ('SENT', 'Sent'),
        ('RESPONDED', 'Responded'),
        ('NO_RESPONSE', 'No Response'),
        ('DECLINED', 'Declined'),
    ]
    line = models.ForeignKey('SolicitationLine', on_delete=models.CASCADE,
                              related_name='rfqs')
    supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.CASCADE,
                                  related_name='dibbs_rfqs')
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    email_sent_to = models.EmailField(null=True, blank=True)   # snapshot of address at send time
    response_received_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    email_message_id = models.CharField(max_length=255, null=True, blank=True)
    follow_up_sent_at = models.DateTimeField(null=True, blank=True)
    follow_up_count = models.IntegerField(default=0)
    notes = models.TextField(null=True, blank=True)
    declined_reason = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'dibbs_supplier_rfq'
```

| Column | Type | Notes |
|--------|------|-------|
| id | INT IDENTITY PK | |
| line_id | INT FK | → dibbs_solicitation_line.id |
| supplier_id | INT FK | → contracts_supplier.id |
| sent_at | DATETIME NULL | When the RFQ email was sent |
| sent_by_id | INT FK | → auth_user |
| email_sent_to | VARCHAR(254) | Snapshot of email address at send time |
| response_received_at | DATETIME NULL | When supplier responded |
| status | VARCHAR(20) | Sent / Responded / No Response / Declined |

#### `dibbs_supplier_quote` *(new)* — pricing received from supplier

```python
class SupplierQuote(models.Model):
    rfq = models.ForeignKey('SupplierRFQ', on_delete=models.CASCADE,
                             related_name='quotes')
    line = models.ForeignKey('SolicitationLine', on_delete=models.CASCADE,
                              related_name='supplier_quotes')
    supplier = models.ForeignKey('contracts.Supplier', on_delete=models.CASCADE,
                                  related_name='dibbs_quotes')
    nsn = models.CharField(max_length=46, db_index=True)   # denormalized for price history
    unit_price = models.DecimalField(max_digits=13, decimal_places=5)
    lead_time_days = models.IntegerField()
    quantity_available = models.IntegerField(null=True, blank=True)
    part_number_offered = models.CharField(max_length=100, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    quote_date = models.DateTimeField(auto_now_add=True)
    entered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    is_selected_for_bid = models.BooleanField(default=False)

    class Meta:
        db_table = 'dibbs_supplier_quote'
```

| Column | Type | Notes |
|--------|------|-------|
| id | INT IDENTITY PK | |
| rfq_id | INT FK | → dibbs_supplier_rfq.id |
| line_id | INT FK | → dibbs_solicitation_line.id (denormalized for fast lookup) |
| supplier_id | INT FK | → contracts_supplier.id (denormalized for price history) |
| nsn | VARCHAR(46) | Denormalized — enables price history queries by NSN across all time |
| unit_price | DECIMAL(13,5) | Supplier's unit price |
| lead_time_days | INT | Supplier's lead time in days |
| quantity_available | INT NULL | |
| part_number_offered | VARCHAR(100) NULL | |
| notes | TEXT NULL | |
| quote_date | DATETIME | Auto-set on creation |
| entered_by_id | INT FK | → auth_user |
| is_selected_for_bid | BIT | Which quote was chosen to submit to DIBBS |

#### `dibbs_government_bid` *(new)* — the bid we submit to DIBBS

```python
class GovernmentBid(models.Model):
    BID_STATUS = [
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
    ]
    solicitation = models.ForeignKey('Solicitation', on_delete=models.CASCADE,
                                      related_name='bids')
    line = models.OneToOneField('SolicitationLine', on_delete=models.CASCADE,
                                 related_name='bid')
    selected_quote = models.ForeignKey('SupplierQuote', on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='bid')
    quoter_cage = models.CharField(max_length=5)
    quote_for_cage = models.CharField(max_length=5)
    bid_type_code = models.CharField(max_length=2)   # BI/BW/AB/DQ
    unit_price = models.DecimalField(max_digits=13, decimal_places=5)
    delivery_days = models.IntegerField()
    manufacturer_dealer = models.CharField(max_length=2)  # MM/DD/QM/QD
    mfg_source_cage = models.CharField(max_length=5, null=True, blank=True)
    fob_point = models.CharField(max_length=1, default='D')
    bid_status = models.CharField(max_length=20, choices=BID_STATUS, default='DRAFT')
    submitted_at = models.DateTimeField(null=True, blank=True)
    exported_bq_file = models.CharField(max_length=255, null=True, blank=True)
    bid_remarks = models.CharField(max_length=255, null=True, blank=True)
    margin_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'dibbs_government_bid'
```

| Column | Type | Notes |
|--------|------|-------|
| id | INT IDENTITY PK | |
| solicitation_id | INT FK | → dibbs_solicitation.id |
| line_id | INT FK (unique) | → dibbs_solicitation_line.id — one bid per line |
| selected_quote_id | INT FK NULL | → dibbs_supplier_quote.id — the quote we priced from |
| quoter_cage | VARCHAR(5) | Our CAGE code |
| quote_for_cage | VARCHAR(5) | Our CAGE or supplier CAGE |
| bid_type_code | CHAR(2) | BI / BW / AB / DQ |
| unit_price | DECIMAL(13,5) | Our bid price |
| delivery_days | INT | Our bid delivery |
| manufacturer_dealer | CHAR(2) | MM/DD/QM/QD |
| mfg_source_cage | VARCHAR(5) NULL | If dealer, actual mfg CAGE |
| fob_point | CHAR(1) | D or O |
| bid_status | VARCHAR(20) | Draft / Submitted / Accepted / Rejected |
| submitted_at | DATETIME NULL | |
| exported_bq_file | VARCHAR(255) NULL | Path/filename of exported BQ file |
| bid_remarks | VARCHAR(255) NULL | BQ Col 121 — only on BW/AB bids |
| margin_pct | DECIMAL(5,2) NULL | Calculated: (bid_price - supplier_price) / bid_price × 100 |

---

### 3.5 NSN Procurement History Table

#### `dibbs_nsn_procurement_history`

Stores historical DLA purchase records per NSN, extracted from DIBBS solicitation ZIP blobs at PDF fetch time. Keyed on `(nsn, contract_number)`.

| Column | Type | Notes |
|--------|------|-------|
| id | INT IDENTITY PK | Surrogate key |
| nsn | VARCHAR(13) | Normalized, no hyphens. FSC+NIIN. Indexed. |
| fsc | CHAR(4) | First 4 chars of NSN. Indexed. |
| cage_code | VARCHAR(5) | Awardee CAGE |
| contract_number | VARCHAR(25) | DLA contract number — unique with nsn |
| quantity | DECIMAL(12,3) | Quantity awarded |
| unit_cost | DECIMAL(14,5) | Unit price at award |
| award_date | DATE | Date of award |
| surplus_material | BIT | Whether surplus material was used |
| first_seen_sol | VARCHAR(13) | Solicitation number where first extracted |
| last_seen_sol | VARCHAR(13) | Solicitation number where most recently seen |
| extracted_at | DATETIME | Last upsert timestamp |

**Design decisions:**

- No FK to `Solicitation`. The data belongs to the NSN; the solicitation is provenance only, stored as a plain varchar.
- Upsert key is `(nsn, contract_number)`. Price/quantity are never overwritten on update — historical fact only. `last_seen_sol` and `extracted_at` update.
- NSN stored normalized (no hyphens). Join to `SolicitationLine.nsn` always uses `_normalize_nsn()` on both sides.
- Extraction runs after a successful download in `fetch_pdf_for_sol()` (same module), and after the RFQ queue persists `pdf_blob` in `rfq_queue_fetch_pdfs`. Wrapped in bare `except Exception` so parse failures never break the PDF fetch.
- The DIBBS "PDF" is actually a ZIP archive with per-page `.txt` files. Text is pre-extracted — no PDF parsing library required.
- History is absent for some solicitation types (pharmaceutical, medical). Empty result is normal and handled silently.

---

## 4. Supplier Matching Engine

When a daily import completes, the matching engine runs automatically and attempts to link each solicitation line to one or more capable suppliers. Three matching tiers are applied in priority order.

**Key asset: contract history for ranking.** `contracts_clin` links NSNs to suppliers. Tier-1 **ranking** uses that history inside the SQL view `dibbs_supplier_nsn_scored` (joined at query time). The Django matching service reads **`SupplierNSNScored`** (unmanaged) and does not import `Clin` in Python.

**Architecture principle:** `contracts` and `sales` remain separate apps. Matching **Python** code reads `dibbs_*` tables and the scored view; the view itself joins `contracts_*` tables inside SQL Server.

### 4.1 Matching Tiers

| Priority | Method | Source Table | Logic |
|----------|--------|-------------|-------|
| 1 — Direct NSN | Exact NSN match | `dibbs_supplier_nsn_scored` (view over `dibbs_supplier_nsn` + `contracts_*`) | Query by NSN on `SupplierNSNScored`, order by `match_score` desc — score computed live in SQL Server |
| 2 — Approved Source | AS file CAGE cross-ref | `dibbs_approved_source` + `contracts_supplier` | Find CAGEs in AS file for this NSN where a matching `contracts_supplier` exists with `archived=False` |
| 3 — FSC Category | 4-digit FSC match | `dibbs_supplier_fsc` | `SupplierFSC.objects.filter(fsc_code=line.fsc, supplier__archived=False)` |

A match result row is written to `dibbs_supplier_match` for each supplier-line pairing found. Tier 1 `match_score` on **`dibbs_supplier_match`** is copied from the scored view at match time. Suppliers with `probation=True` or `conditional=True` are included but visually flagged. Suppliers with `archived=True` are excluded entirely.

**`match_score` on `dibbs_supplier_match`:**
```python
match_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
# Tier 1: from SupplierNSNScored / view dibbs_supplier_nsn_scored (live SQL formula; see §12.3)
# Tier 2: 1.0 fixed (approved source is a strong signal)
# Tier 3: 0.5 fixed (FSC is a weak/broad signal)
```

### 4.2 Live NSN scoring (SQL view)

- **`dibbs_supplier_nsn`** holds only rows users/system create (bulk NSN add, quote-confirmed `get_or_create`, etc.). There is **no** `contract_history` sync job and **no** Python backfill.
- **`dibbs_supplier_nsn_scored`** is a SQL Server **view** (see `sales/sql/dibbs_supplier_nsn_scored.sql`). Deploy with SSMS (`CREATE OR ALTER VIEW`). Do not run the `.sql` file from Django or management commands.
- Matching tier 1 queries this view via Django unmanaged model **`SupplierNSNScored`**.

```
ONGOING:
Staff / quotes ──→ dibbs_supplier_nsn
                          │
                          ▼
contracts_clin + contracts_contract + contracts_nsn ──→ dibbs_supplier_nsn_scored (VIEW)
                          │
                          ▼
              matching.py (SupplierNSNScored) ──→ dibbs_supplier_match
```

#### `dibbs_supplier_match` *(new)* — results of matching engine

```python
class SupplierMatch(models.Model):
    MATCH_METHOD = [
        ('DIRECT_NSN', 'Direct NSN'),
        ('APPROVED_SOURCE', 'Approved Source'),
        ('FSC', 'FSC Category'),
    ]
    line = models.ForeignKey('SolicitationLine', on_delete=models.CASCADE,
                              related_name='supplier_matches')
    supplier = models.ForeignKey('contracts.Supplier', on_delete=models.CASCADE,
                                  related_name='dibbs_matches')
    match_tier = models.IntegerField()   # 1, 2, or 3
    match_method = models.CharField(max_length=20, choices=MATCH_METHOD)
    is_excluded = models.BooleanField(default=False)  # staff can exclude before RFQ send
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dibbs_supplier_match'
        unique_together = ('line', 'supplier')
```

| Column | Type | Notes |
|--------|------|-------|
| id | INT IDENTITY PK | |
| line_id | INT FK | → dibbs_solicitation_line.id |
| supplier_id | INT FK | → contracts_supplier.id |
| match_tier | INT | 1, 2, or 3 |
| match_method | VARCHAR(20) | DirectNSN / ApprovedSource / FSC |
| is_excluded | BIT | Staff can exclude a match before RFQ send |
| created_at | DATETIME | Auto-set on creation |

**Matching filter rules applied to `contracts_supplier`:**

| Supplier Flag | Behavior |
|--------------|---------|
| `archived = True` | Excluded from matching entirely — never returned |
| `probation = True` | Included but flagged ⚠ in UI — staff must manually approve RFQ |
| `conditional = True` | Included but flagged ⚠ in UI — staff must manually approve RFQ |
| All clear | Eligible for automatic RFQ dispatch |

---

## 5. BQ Batch Quote Export Engine

The export engine takes completed bid records from `tbl_GovernmentBid` and produces a valid BQ-format CSV file for upload to DIBBS. The file must conform exactly to the 121-column specification.

### 5.1 Field Mapping — Company-Filled Fields

The BQ file arrives from DIBBS with most fields pre-filled. The following columns are the ones your system must populate:

| BQ Col # | Field Name | Source in Our DB | Notes |
|----------|-----------|-----------------|-------|
| 6 | Quoter CAGE Code | tbl_GovernmentBid.QuoterCAGE | Your registered CAGE |
| 7 | Quote For CAGE Code | tbl_GovernmentBid.QuoteForCAGE | May differ if quoting on behalf of supplier |
| 13 | SB Representations Code | Company settings | A/B/C/E/F/G/M/P/X |
| 21 | Affirmative Action Code | Company settings | Y6/N6/NH/NA |
| 22 | Previous Contracts Code | Company settings | Y4/Y5/N4/NA |
| 23 | Alternate Disputes Resolution | Company settings | A or B |
| 24 | Bid Type Code | tbl_GovernmentBid.BidTypeCode | BI/BW/AB/DQ |
| 50 | Unit Price | tbl_GovernmentBid.UnitPrice | 0.00000 to 9999999.99999 |
| 51 | Delivery Days | tbl_GovernmentBid.DeliveryDays | 0–9999 |
| 65 | Hazardous Material | tbl_GovernmentBid or company default | N/Y |
| 67 | Material Requirements | tbl_GovernmentBid | 0=New, 1–4=other |
| 70 | Buy American End Product | tbl_GovernmentBid | D/Q/NQ etc. |
| 102 | Manufacturer/Dealer | tbl_GovernmentBid.ManufacturerDealer | MM/DD/QM/QD |
| 103 | Actual Mfg CAGE | tbl_GovernmentBid.MfgSourceCAGE | Required when DD or QD |
| 106 | Part Number Offered Code | tbl_GovernmentBid | 1–9, A |
| 107 | Part Number Offered CAGE | tbl_GovernmentBid | When item desc = P/B/N |
| 108 | Part Number Offered | tbl_GovernmentBid | When item desc = P/B/N |
| 118 | Higher-Level Quality Code | tbl_GovernmentBid | Required when col 117 ≠ N |
| 120 | Child Labor Certification | Company default = N | N/U/Y |
| 121 | Quote Remarks | tbl_GovernmentBid.BidRemarks | Only allowed on BW/AB bids |

### 5.2 Export Process

1. User selects one or more solicitations with status **Bid Ready**
2. System loads the BQ template row from `tbl_SolicitationLine` (the original pre-filled DIBBS data)
3. Merges vendor-entered fields from `tbl_GovernmentBid`
4. Validates all 121 columns against the DIBBS ruleset before export
5. Outputs a valid `.txt` file named `bq[YYMMDD].txt` ready for DIBBS upload
6. Updates bid status to **Submitted** and records the export filename

---

## 6. Django Application Structure

### 6.0 One App: `sales`

All DIBBS functionality lives in the single `sales` app already added to `INSTALLED_APPS`. The earlier design proposed 8 separate Django apps (`imports`, `solicitations`, `matching`, `rfq`, etc.) but that was over-engineered for this use case:

- All modules are tightly coupled — matching needs solicitations, quoting needs RFQs, bids need quotes. Separate apps would create constant cross-app import friction.
- Each proposed app had only 2–4 models and a handful of views — not enough mass to justify independent registration.
- The existing project's own apps (`contracts`, `inventory`, `processing`, etc.) follow a monolithic single-app pattern. `sales` should match that convention.
- Django app boundaries are designed for genuinely reusable, independently deployable modules. None of the DIBBS sub-modules qualify.

Organization that matters is achieved through **Python module structure within `sales`**, not Django app boundaries.

### 6.1 `sales` App Internal Structure

```
sales/
├── apps.py
├── admin.py
├── forms.py
├── urls.py
│
├── models/
│   ├── __init__.py          # re-exports all models so imports work as normal
│   ├── solicitations.py     # Solicitation, SolicitationLine, ImportBatch
│   ├── approved_sources.py  # ApprovedSource
│   ├── matching.py          # SupplierMatch
│   ├── rfq.py               # SupplierRFQ, SupplierContactLog
│   ├── quotes.py            # SupplierQuote
│   ├── bids.py              # GovernmentBid
│   └── cages.py             # CompanyCAGE
│
├── views/
│   ├── __init__.py
│   ├── dashboard.py
│   ├── imports.py           # IN/BQ/AS file upload and processing
│   ├── solicitations.py     # browse, search, detail
│   ├── rfq.py               # RFQ center, send, track, quote entry
│   ├── bids.py              # bid builder, BQ export
│   └── suppliers.py         # DIBBS-specific supplier views (NSN/FSC capabilities)
│
├── services/
│   ├── __init__.py
│   ├── parser.py            # IN/BQ/AS file parsing logic
│   ├── matching.py          # 3-tier supplier matching engine
│   ├── email.py             # RFQ email generation and dispatch
│   └── bq_export.py         # 121-column BQ file assembly and validation
│
└── templates/
    └── sales/
        ├── base.html
        ├── dashboard.html
        ├── solicitations/
        ├── rfq/
        ├── bids/
        └── suppliers/
```

### 6.2 Relationship to Existing Apps

The `sales` app reads from but does not modify data owned by other apps:

| Existing App | Table | How `sales` uses it |
|---|---|---|
| `suppliers` | `contracts_supplier` | FK target for all supplier relationships. Note: table name is `contracts_supplier` because `Supplier` was historically part of the `contracts` app before being split out. The model now lives in `suppliers` — import it as `from suppliers.models import Supplier`. |
| `contracts` | Various | Read-only reference where relevant (e.g. existing contract history) |
| `users` | `auth_user` | FK for `logged_by`, `sent_by`, `entered_by` audit fields on DIBBS records |

No other app should import from `sales`. Data flows one way: existing apps provide supplier and user context; `sales` owns the entire DIBBS pipeline on top of that.

### 6.3 Key Model Relationships

```
contracts_supplier  ←──────────────────────────────────────────────┐
                                                                    │ (FK on all new tables)
dibbs_solicitation                                                  │
  └── dibbs_solicitation_line (one-to-many)                        │
        ├── dibbs_supplier_match (one-to-many, via matching engine) ┤
        │     └── dibbs_supplier_rfq (one-to-one when RFQ sent)    ┤
        │           └── dibbs_supplier_quote (one-to-many)         ┘
        └── dibbs_government_bid (one-to-one when bid assembled)
              └── selected_quote → dibbs_supplier_quote (for margin tracking)
```

### 6.4 Company Settings

A single-row settings table stores company-level defaults applied to every bid export:

| Setting | Example Value |
|---------|--------------|
| QuoterCAGECode | 1AB2C |
| SmallBusinessRepCode | B |
| AffirmativeActionCode | Y6 |
| PreviousContractsCode | Y4 |
| AlternateDisputesResolution | A |
| DefaultFOBPoint | D |
| DefaultPaymentTerms | 1 (Net 30) |
| DefaultChildLaborCode | N |
| SMTPHost / SMTPPort | mail.company.com / 587 |
| RFQEmailFromAddress | bids@company.com |
| DefaultMarkupPct | 20.00 |

---

## 7. Phased Delivery Plan

Given the urgency of replacing the retiring system, work is organized into three phases. **Phase 1 alone restores core bidding capability.**

### Phase 1 — Critical Path (Weeks 1–2)

- Django project setup + SQL Server connection
- IN / BQ / AS file parser & daily import
- Solicitation browse & search UI
- Supplier database (import existing supplier data)
- Manual BQ field entry + export
- Basic bid status tracking

### Phase 2 — Core Automation (Weeks 3–4)

- Matching engine (Tier 1 Direct NSN + Tier 2 Approved Source + Tier 3 FSC)
- Automated RFQ email generation and dispatch
- Supplier quote entry interface
- Price history per NSN
- Bid assembly with margin calculation

### Phase 3 — Polish & Reporting (Weeks 5–6)

- BQ export validation engine (full 121-column ruleset)
- Win/loss reporting and analytics
- Price history trending charts
- Bulk actions (no-bid batches, mass RFQ send)
- Role-based access control

> ⚠ **Phase 1 focus:** Get a working system that can import daily files and export a valid BQ upload file. Everything else follows.

---

## 8. Resolved Decisions & Constraints

All architecture questions have been answered. These decisions are locked into the design.

| # | Decision | Resolution | Design Impact |
|---|----------|-----------|---------------|
| 1 | Supplier data migration | **No migration needed.** Existing `contracts_supplier` table is already populated and in production. New bidding tables FK directly into it. | Phase 1 scope reduced — supplier data is ready on day one |
| 2 | Multi-user & deployment | **2–5 concurrent internal users.** Hosted on the existing internal cloud. No public internet exposure. Security, auth, and infrastructure already in place via the existing Django project. This is an add-on app — not a new deployment. | No new infrastructure work needed. Standard Django session auth applies. |
| 3 | CAGE codes | **Multiple CAGE codes.** The company may bid under more than one registered CAGE. | `dibbs_company_cage` settings table required (see Section 6.2). BQ export must let user select the active CAGE per bid or per session. |
| 4 | Markup / pricing formula | **Default 3.5% markup over supplier cost, but variable.** Margin is adjusted based on competitive conditions per solicitation. | Bid assembly UI must show the calculated price at 3.5% as a starting point but allow the user to override per line. `margin_pct` is stored on `dibbs_government_bid` for post-award analysis. |
| 5 | Daily file download | **Manual download.** Staff downloads IN, BQ, and AS files from DIBBS each day and uploads them into the system. No auto-fetch. | Import module accepts file uploads via the UI. Files are validated by name format (`in[YYMMDD].txt`, `bq[YYMMDD].txt`, `as[YYMMDD].txt`) on upload. Auto-fetch can be added later if DIBBS access allows. |
| 6 | RFQ dispatch | **Manual approval required — no auto-send.** After matching runs, staff reviews matches and manually triggers RFQ emails. Automated dispatch is a future option. | Matching engine writes to `dibbs_supplier_match` and stops. A separate **RFQ Review** screen shows all pending matches grouped by solicitation. Staff clicks "Send RFQs" per solicitation or per supplier. The automated pathway is architected but gated behind a feature flag so it can be enabled later without a redesign. |

### 8.1 Company CAGE Settings

Because multiple CAGE codes are in use, company-level settings are stored per CAGE rather than as a single global row:

#### `dibbs_company_cage` *(new)* — one row per registered CAGE code

```python
class CompanyCAGE(models.Model):
    cage_code = models.CharField(max_length=5, unique=True)
    company_name = models.CharField(max_length=150)
    sb_representations_code = models.CharField(max_length=1)   # A/B/C/E/F/G/M/P/X
    affirmative_action_code = models.CharField(max_length=2)   # Y6/N6/NH/NA
    previous_contracts_code = models.CharField(max_length=2)   # Y4/Y5/N4/NA
    alternate_disputes_resolution = models.CharField(max_length=1)  # A or B
    default_fob_point = models.CharField(max_length=1, default='D')
    default_payment_terms = models.CharField(max_length=2, default='1')
    default_child_labor_code = models.CharField(max_length=1, default='N')
    default_markup_pct = models.DecimalField(max_digits=5, decimal_places=2, default=3.50)
    is_default = models.BooleanField(default=False)  # pre-selected in bid UI
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'dibbs_company_cage'
```

| Column | Type | Notes |
|--------|------|-------|
| id | INT IDENTITY PK | |
| cage_code | VARCHAR(5) UNIQUE | Registered CAGE — BQ col 6 / col 7 |
| company_name | VARCHAR(150) | |
| sb_representations_code | CHAR(1) | BQ col 13 |
| affirmative_action_code | CHAR(2) | BQ col 21 |
| previous_contracts_code | CHAR(2) | BQ col 22 |
| alternate_disputes_resolution | CHAR(1) | BQ col 23 |
| default_fob_point | CHAR(1) | BQ col 32 — default D |
| default_payment_terms | CHAR(2) | BQ col 25 — default 1 (Net 30) |
| default_child_labor_code | CHAR(1) | BQ col 120 — default N |
| default_markup_pct | DECIMAL(5,2) | Default 3.50 — overridable per bid |
| is_default | BIT | Pre-selected CAGE in the bid assembly UI |
| is_active | BIT | Soft disable without deleting |

### 8.2 Markup / Pricing Logic

The bid assembly screen applies the following pricing flow:

```
supplier_unit_price
  × (1 + default_markup_pct / 100)     ← starting point, e.g. × 1.035
  = suggested_bid_price                 ← pre-filled in the unit price field
  → user overrides as needed            ← final bid_price saved to dibbs_government_bid
  → margin_pct recalculated on save     ← (bid_price - supplier_price) / bid_price × 100
```

This means 3.5% is a floor suggestion, not a hard rule. The stored `margin_pct` lets you report on actual achieved margins per NSN, per supplier, and over time.

### 8.3 RFQ Dispatch Workflow (Manual Mode)

The current implementation uses **manual approval**. The flow is:

1. Daily import runs → matching engine populates `dibbs_supplier_match`
2. Staff opens **RFQ Review** screen — shows all new matches grouped by solicitation
3. Probation/conditional suppliers are flagged ⚠ — staff decides whether to include
4. Staff clicks **Send RFQs** for a solicitation (or selects individual suppliers)
5. System generates RFQ emails and sets `dibbs_supplier_rfq.status = SENT`
6. A `auto_dispatch_enabled` boolean on `CompanyCAGE` (or a Django setting) gates the automated pathway for future use

**Email transport:** The system uses Microsoft Graph API (`GRAPH_MAIL_ENABLED=True`) for automated outbound RFQ dispatch from `quotes@statzcorp.com`. When Graph is unavailable or disabled, the queue send flow generates `mailto:` URLs that open in the user's local email client (Outlook). The user sends manually and clicks **Mark All Sent** to confirm. Both paths log `SupplierContactLog` entries and advance `SupplierRFQ` status to `SENT`. The Graph app registration is **STATZ Web App Mail** in the `statzcorpgcch` tenant with **Mail.Send** application permission for outbound sends and **Mail.Read** (or **Mail.ReadWrite**) for the RFQ Inbox reader (`services/graph_inbox.py`), which lists messages in the `GRAPH_MAIL_SENDER` mailbox (GCC High: `graph.microsoft.us`).

**Sender mailbox decision (standing):** `quotes@statzcorp.com` is the designated production RFQ sender. This address was used by the legacy Sales Patriot platform; suppliers have existing email relationships with it and it carries established sending reputation in the M365 tenant. Switching the production sender requires sales team sign-off. `rfq@statzcorp.com` is the designated dev/test sender — it is a mature mailbox with sending history (critical: newly provisioned accounts are flagged as spam almost immediately at cold RFQ volumes). Environment separation is enforced via `GRAPH_MAIL_SENDER`: `quotes@statzcorp.com` in Azure App Service production config, `rfq@statzcorp.com` in local `.env`.

---

*DIBBS Government Bidding System — Technical Specification v1.0 — March 2026*


---

## 9. Application Flow & Page Tree

### 9.1 Page Tree

The Sales App uses an 8-item primary navigation bar (Dashboard, Solicitations, RFQ Center, Bid Center, Suppliers, Import, Awards, Settings). RFQ Center, Bid Center, and Settings also render a server-side secondary sub-nav (via the `section` view context variable) directly beneath the primary bar.

```
SALES APP
│
├── 🏠  Dashboard                          /sales/
│         Today's pipeline at a glance
│         Stat cards, urgent actions, recent activity
│
├── 📥  Daily Import                       /sales/import/
│    ├── Upload Files                      /sales/import/upload/
│    │         Drop IN + BQ + AS files together
│    │         Validates filenames & date match
│    │         Shows import preview before commit
│    └── Import History                    /sales/import/history/
│              All past import batches with row counts
│
├── 📋  Solicitations                      /sales/solicitations/
│    ├── Browse / Filter                   /sales/solicitations/           (default view)
│    │         Master list — search, filter, sort
│    │         Columns: Solicitation #, NSN, Nomenclature,
│    │                  Qty, Return Date, Set-Aside, Status
│    │         Status badge colors at a glance
│    ├── Closed Solicitations              /sales/solicitations/closed/
│    │         Read-only terminal outcomes: NO_BID, Archived, BID_SUBMITTED, WON, LOST
│    │         Status tabs via ?status= (no_bid, archived, bid_submitted, won, lost; omit for all)
│    │         Legacy /sales/solicitations/archive/ redirects here (301)
│    ├── Solicitation Detail               /sales/solicitations/<sol#>/
│    │    ├── Overview tab                 NSN, PR#, return date, PDF link
│    │    ├── Matches tab                  Matched suppliers with tier badges
│    │    ├── RFQs tab                     Sent RFQs + supplier responses
│    │    ├── Quotes tab                   All supplier pricing received
│    │    └── Bid tab                      Assemble & export government bid
│    └── No-Bid Queue                      /sales/solicitations/nobid/
│              Solicitations marked DQ — bulk no-bid action
│
├── 🏭  Suppliers                          /sales/suppliers/
│    ├── Supplier List                     /sales/suppliers/
│    │         Search by name, CAGE, FSC
│    │         Flags: ⚠ Probation, ⚠ Conditional, ✗ Archived
│    ├── Supplier Detail                   /sales/suppliers/<id>/
│    │    ├── Profile tab                  Contact info, CAGE, address (read from contracts_supplier)
│    │    ├── Capabilities tab             NSNs and FSC codes this supplier covers
│    │    ├── Quote History tab            All past quotes with prices + dates
│    │    └── Bid Performance tab          Win/loss record for this supplier's parts
│    ├── Add NSN Capability               /sales/suppliers/<id>/nsn/add/
│    └── Add FSC Capability               /sales/suppliers/<id>/fsc/add/
│
├── 📨  RFQ Center                         /sales/rfq/queue/
│    ├── Queue (sub-nav)                   /sales/rfq/queue/               (default view)
│    │         All queued RFQs grouped by supplier
│    ├── Manage (sub-nav)                  /sales/rfq/center/
│    │         3-panel RFQ management workflow
│    ├── Inbox (sub-nav)                   /sales/rfq/inbox/
│    │         Supplier mailbox replies linked to RFQs
│    ├── Pending Review                    /sales/rfq/pending/
│    ├── Sent RFQs                         /sales/rfq/sent/
│    └── Enter Supplier Quote              /sales/rfq/<rfq_id>/quote/
│
├── 💰  Bid Center                         /sales/bids/
│    ├── Active (sub-nav)                  /sales/bids/                    (default view)
│    │         Lines with at least one supplier quote, no bid yet
│    │         Shows best supplier price + suggested bid at 3.5%
│    ├── Bid Builder                       /sales/bids/<sol#>/build/
│    │         Per-line bid assembly
│    │         CAGE selector, price override, all 121 BQ fields
│    ├── Export Queue                      /sales/bids/export/
│    │         Bids marked ready — select and export BQ file
│    └── Bid History (sub-nav)             /sales/bids/history/
│              All submitted bids with outcome tracking
│
└── ⚙️  Settings                           /sales/settings/
     ├── CAGEs (sub-nav)                   /sales/settings/cages/
     │         Manage registered CAGE codes and their defaults
     ├── No Quote CAGEs (sub-nav)          /sales/settings/no-quote/
     ├── Email Templates (sub-nav)         /sales/settings/email/
     ├── Greetings (sub-nav)               /sales/settings/greetings/
     └── Salutations (sub-nav)             /sales/settings/salutations/

Notes:
- Secondary sub-nav is rendered server-side from template conditionals based on `section` (`'rfq'`, `'bids'`, `'settings'`).
- No JavaScript controls sub-nav visibility.
- Bid History, No Quote CAGEs, and Email Templates are sub-nav destinations, not primary-nav items.
```

### 9.2 Navigation & Status Flow

A solicitation moves through the following statuses, each corresponding to a zone in the app:

```
  [NEW]
    │   Daily import creates solicitation
    ▼
  [MATCHING]
    │   Matching engine runs automatically post-import
    ▼
  [RFQ PENDING]  ←── RFQ Center / Pending Review
    │   Staff reviews matches, sends RFQ emails
    ▼
  [RFQ SENT]     ←── RFQ Center / Sent RFQs
    │   Waiting on supplier responses
    ▼
  [QUOTING]      ←── RFQ Center / Enter Supplier Quote
    │   Supplier pricing entered into system
    ▼
  [BID READY]    ←── Bid Center / Ready to Bid
    │   Bid assembled, price set
    ▼
  [BID SUBMITTED] ←── Bid Center / Export Queue
    │   BQ file exported and uploaded to DIBBS
    ▼
  [WON / LOST / NO BID]  ←── Bid Center / Bid History
```

---

## 9.3 Design Vision & Visual Language

### Aesthetic Direction: **"Mission Operations"**

This is internal government procurement software — serious, fast, high-stakes. The design draws from mission control interfaces and military logistics systems: dense information handled with absolute clarity. No decoration for decoration's sake. Every pixel earns its place.

**The one thing users will remember:** The status pipeline strip at the top of every solicitation — a horizontal progress track that shows exactly where a deal is in the pipeline at a glance, like a flight progress bar. It makes abstract workflow states physical and spatial.

**Tone:** Industrial precision. Confident. Dark sidebar, bright data surface. The kind of interface that feels like the people using it know exactly what they're doing.

**Palette:**
```
--navy:        #0A1628   /* Sidebar, deepest backgrounds */
--navy-mid:    #112240   /* Card backgrounds, secondary surfaces */
--steel:       #1B3A6B   /* Active states, hover fills */
--accent:      #00B4D8   /* Primary action color — electric cyan */
--accent-warm: #F4A261   /* Warning states, deadlines approaching */
--danger:      #E63946   /* Overdue, errors, no-bid */
--success:     #2DC653   /* Won, submitted, matched */
--text-primary:#E8EDF5   /* Main text on dark */
--text-muted:  #7A90B0   /* Secondary labels, metadata */
--surface:     #F0F4F8   /* Main content area background (light) */
--border:      #1E3A5F   /* Sidebar borders */
```

**Typography:**
- Display / headings: `Barlow Condensed` (free, Google Fonts) — narrow, authoritative, reads like a military stencil
- Body / data: `IBM Plex Mono` (free, Google Fonts) — monospaced data feels honest; NSNs, prices, CAGE codes look right in mono
- UI labels: `Barlow` regular — same family, comfortable for forms and navigation

---

## 9.4 Base Layout — Sidebar Shell

This is the persistent shell that wraps every page in the app. All pages render inside `{% block content %}`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Sales{% endblock %} — DIBBS Sales</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --navy:        #0A1628;
      --navy-mid:    #112240;
      --steel:       #1B3A6B;
      --accent:      #00B4D8;
      --accent-warm: #F4A261;
      --danger:      #E63946;
      --success:     #2DC653;
      --text-primary:#E8EDF5;
      --text-muted:  #7A90B0;
      --surface:     #F0F4F8;
      --border:      #1E3A5F;
      --sidebar-w:   240px;
    }

    body {
      font-family: 'Barlow', sans-serif;
      background: var(--surface);
      color: #1a2940;
      display: flex;
      min-height: 100vh;
    }

    /* ── SIDEBAR ─────────────────────────────────── */
    .sidebar {
      width: var(--sidebar-w);
      background: var(--navy);
      display: flex;
      flex-direction: column;
      position: fixed;
      top: 0; left: 0; bottom: 0;
      z-index: 100;
      border-right: 1px solid var(--border);
    }

    .sidebar-logo {
      padding: 24px 20px 20px;
      border-bottom: 1px solid var(--border);
    }

    .sidebar-logo .app-name {
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 22px;
      font-weight: 700;
      color: var(--accent);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .sidebar-logo .app-sub {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      color: var(--text-muted);
      letter-spacing: 0.08em;
      margin-top: 2px;
    }

    .sidebar-nav {
      flex: 1;
      padding: 16px 0;
      overflow-y: auto;
    }

    .nav-section-label {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      color: var(--text-muted);
      letter-spacing: 0.12em;
      text-transform: uppercase;
      padding: 12px 20px 6px;
    }

    .nav-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 20px;
      color: var(--text-muted);
      text-decoration: none;
      font-size: 14px;
      font-weight: 500;
      transition: background 0.15s, color 0.15s;
      border-left: 3px solid transparent;
      position: relative;
    }

    .nav-item:hover {
      background: var(--steel);
      color: var(--text-primary);
      border-left-color: var(--steel);
    }

    .nav-item.active {
      background: rgba(0,180,216,0.12);
      color: var(--accent);
      border-left-color: var(--accent);
    }

    .nav-item .nav-icon {
      font-size: 16px;
      width: 20px;
      text-align: center;
      flex-shrink: 0;
    }

    .nav-badge {
      margin-left: auto;
      background: var(--danger);
      color: white;
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      font-weight: 500;
      padding: 2px 6px;
      border-radius: 10px;
      min-width: 20px;
      text-align: center;
    }

    .nav-badge.warn { background: var(--accent-warm); color: #1a0a00; }
    .nav-badge.ok   { background: var(--success); color: #001a08; }

    .sidebar-footer {
      padding: 16px 20px;
      border-top: 1px solid var(--border);
    }

    .user-chip {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .user-avatar {
      width: 32px; height: 32px;
      border-radius: 50%;
      background: var(--steel);
      display: flex; align-items: center; justify-content: center;
      font-family: 'Barlow Condensed', sans-serif;
      font-weight: 700;
      font-size: 13px;
      color: var(--accent);
      flex-shrink: 0;
    }

    .user-name {
      font-size: 13px;
      font-weight: 500;
      color: var(--text-primary);
    }

    .user-role {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      color: var(--text-muted);
    }

    /* ── MAIN CONTENT ────────────────────────────── */
    .main {
      margin-left: var(--sidebar-w);
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }

    .topbar {
      background: white;
      border-bottom: 1px solid #dde3ec;
      padding: 0 32px;
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 50;
    }

    .topbar-breadcrumb {
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 18px;
      font-weight: 600;
      color: #1a2940;
      letter-spacing: 0.02em;
    }

    .topbar-breadcrumb .crumb-sep {
      color: #a0aec0;
      margin: 0 6px;
    }

    .topbar-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .import-date-chip {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 11px;
      color: var(--text-muted);
      background: #eef2f8;
      padding: 4px 10px;
      border-radius: 4px;
      border: 1px solid #dde3ec;
    }

    .page-body {
      padding: 32px;
      flex: 1;
    }

    /* ── BUTTONS ─────────────────────────────────── */
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 16px;
      border-radius: 5px;
      font-family: 'Barlow', sans-serif;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      text-decoration: none;
      transition: opacity 0.15s, transform 0.1s;
    }

    .btn:hover { opacity: 0.88; transform: translateY(-1px); }
    .btn:active { transform: translateY(0); }

    .btn-primary  { background: var(--accent);      color: #001a22; }
    .btn-navy     { background: var(--navy);         color: var(--text-primary); }
    .btn-danger   { background: var(--danger);       color: white; }
    .btn-ghost    { background: transparent; border: 1px solid #c8d3e0; color: #3a5070; }
    .btn-success  { background: var(--success);      color: #001a08; }
    .btn-sm       { padding: 5px 11px; font-size: 12px; }

    /* ── STAT CARDS ──────────────────────────────── */
    .stat-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }

    .stat-card {
      background: white;
      border-radius: 8px;
      padding: 20px;
      border: 1px solid #dde3ec;
      position: relative;
      overflow: hidden;
    }

    .stat-card::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
    }

    .stat-card.accent::before  { background: var(--accent); }
    .stat-card.warn::before    { background: var(--accent-warm); }
    .stat-card.danger::before  { background: var(--danger); }
    .stat-card.success::before { background: var(--success); }
    .stat-card.navy::before    { background: var(--navy); }

    .stat-label {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #7a90b0;
      margin-bottom: 8px;
    }

    .stat-value {
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 36px;
      font-weight: 700;
      color: #0a1628;
      line-height: 1;
    }

    .stat-sub {
      font-size: 12px;
      color: #7a90b0;
      margin-top: 4px;
    }

    /* ── TABLES ──────────────────────────────────── */
    .data-table-wrap {
      background: white;
      border-radius: 8px;
      border: 1px solid #dde3ec;
      overflow: hidden;
    }

    .table-header {
      padding: 16px 20px;
      border-bottom: 1px solid #eef2f8;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .table-title {
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 16px;
      font-weight: 600;
      color: #1a2940;
      letter-spacing: 0.02em;
    }

    .search-input {
      padding: 7px 12px;
      border: 1px solid #dde3ec;
      border-radius: 5px;
      font-size: 13px;
      font-family: 'IBM Plex Mono', monospace;
      width: 260px;
      background: #f7f9fc;
      color: #1a2940;
      outline: none;
      transition: border-color 0.15s;
    }

    .search-input:focus { border-color: var(--accent); background: white; }
    .search-input::placeholder { color: #a0aec0; }

    table { width: 100%; border-collapse: collapse; }

    thead th {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #7a90b0;
      padding: 10px 16px;
      text-align: left;
      background: #f7f9fc;
      border-bottom: 1px solid #eef2f8;
      white-space: nowrap;
    }

    tbody tr {
      border-bottom: 1px solid #eef2f8;
      transition: background 0.1s;
      cursor: pointer;
    }

    tbody tr:last-child { border-bottom: none; }
    tbody tr:hover { background: #f0f7ff; }

    tbody td {
      padding: 11px 16px;
      font-size: 13px;
      color: #1a2940;
      vertical-align: middle;
    }

    .mono { font-family: 'IBM Plex Mono', monospace; font-size: 12px; }

    /* ── STATUS BADGES ───────────────────────────── */
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 8px;
      border-radius: 4px;
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      font-weight: 500;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }

    .badge-new        { background: #e8f4fd; color: #1565c0; border: 1px solid #bbdefb; }
    .badge-matching   { background: #fff8e1; color: #f57f17; border: 1px solid #ffe082; }
    .badge-rfq-pend   { background: #fff3e0; color: #e65100; border: 1px solid #ffcc02; }
    .badge-rfq-sent   { background: #e3f2fd; color: #0277bd; border: 1px solid #90caf9; }
    .badge-quoting    { background: #f3e5f5; color: #6a1b9a; border: 1px solid #ce93d8; }
    .badge-bid-ready  { background: #e0f7fa; color: #00695c; border: 1px solid #80cbc4; }
    .badge-submitted  { background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }
    .badge-won        { background: #1b5e20; color: #69f0ae; border: 1px solid #2e7d32; }
    .badge-lost       { background: #fce4ec; color: #880e4f; border: 1px solid #f48fb1; }
    .badge-no-bid     { background: #f5f5f5; color: #616161; border: 1px solid #bdbdbd; }
    .badge-tier1      { background: rgba(0,180,216,0.12); color: #00b4d8; border: 1px solid rgba(0,180,216,0.3); }
    .badge-tier2      { background: rgba(244,162,97,0.12); color: #e07c3a; border: 1px solid rgba(244,162,97,0.3); }
    .badge-tier3      { background: rgba(122,144,176,0.12); color: #5a7090; border: 1px solid rgba(122,144,176,0.3); }
    .badge-warn       { background: #fff3e0; color: #bf360c; }
    .badge-sb         { background: #e8eaf6; color: #283593; border: 1px solid #9fa8da; }

    /* ── PIPELINE TRACK ──────────────────────────── */
    .pipeline-track {
      display: flex;
      align-items: center;
      gap: 0;
      background: white;
      border: 1px solid #dde3ec;
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 24px;
    }

    .pipeline-step {
      flex: 1;
      padding: 12px 8px;
      text-align: center;
      position: relative;
      background: #f7f9fc;
      border-right: 1px solid #dde3ec;
      transition: background 0.2s;
    }

    .pipeline-step:last-child { border-right: none; }

    .pipeline-step.active {
      background: var(--navy);
    }

    .pipeline-step.done {
      background: rgba(45,198,83,0.08);
    }

    .pipeline-step .step-icon {
      font-size: 18px;
      display: block;
      margin-bottom: 4px;
    }

    .pipeline-step .step-label {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #a0aec0;
    }

    .pipeline-step.active .step-label { color: var(--accent); }
    .pipeline-step.done .step-label   { color: var(--success); }

    /* ── TABS ────────────────────────────────────── */
    .tab-bar {
      display: flex;
      border-bottom: 2px solid #eef2f8;
      margin-bottom: 24px;
      gap: 0;
    }

    .tab-item {
      padding: 10px 20px;
      font-size: 13px;
      font-weight: 600;
      color: #7a90b0;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -2px;
      text-decoration: none;
      transition: color 0.15s;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .tab-item:hover { color: #1a2940; }

    .tab-item.active {
      color: var(--navy);
      border-bottom-color: var(--accent);
    }

    .tab-count {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      background: #eef2f8;
      padding: 1px 5px;
      border-radius: 10px;
      color: #5a7090;
    }

    .tab-item.active .tab-count {
      background: rgba(0,180,216,0.12);
      color: var(--accent);
    }

    /* ── ALERT BANNERS ───────────────────────────── */
    .alert {
      padding: 12px 16px;
      border-radius: 6px;
      font-size: 13px;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      border-left: 4px solid;
    }

    .alert-warn   { background: #fff8f0; border-color: var(--accent-warm); color: #7a3500; }
    .alert-danger { background: #fff0f1; border-color: var(--danger);      color: #7a0010; }
    .alert-info   { background: #f0faff; border-color: var(--accent);      color: #003a4a; }
    .alert-ok     { background: #f0fff4; border-color: var(--success);     color: #00401a; }

    /* ── FORMS ───────────────────────────────────── */
    .form-card {
      background: white;
      border: 1px solid #dde3ec;
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 20px;
    }

    .form-section-title {
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--navy);
      border-bottom: 1px solid #eef2f8;
      padding-bottom: 10px;
      margin-bottom: 18px;
    }

    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 16px;
    }

    .form-group { display: flex; flex-direction: column; gap: 5px; }

    .form-label {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #5a7090;
      font-weight: 500;
    }

    .form-control {
      padding: 8px 11px;
      border: 1px solid #dde3ec;
      border-radius: 5px;
      font-size: 13px;
      font-family: 'IBM Plex Mono', monospace;
      background: #f7f9fc;
      color: #1a2940;
      outline: none;
      transition: border-color 0.15s, background 0.15s;
    }

    .form-control:focus { border-color: var(--accent); background: white; }

    select.form-control { cursor: pointer; }

    .form-control.price-field {
      font-weight: 500;
      font-size: 15px;
      color: #0a1628;
    }

    .form-hint {
      font-size: 11px;
      color: #a0aec0;
      font-family: 'IBM Plex Mono', monospace;
    }

    /* ── PRICE COMPARISON CARD ───────────────────── */
    .price-compare {
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 16px;
      align-items: center;
      background: white;
      border: 1px solid #dde3ec;
      border-radius: 8px;
      padding: 20px 24px;
      margin-bottom: 20px;
    }

    .price-block { text-align: center; }

    .price-block .price-label {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 10px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #7a90b0;
      margin-bottom: 6px;
    }

    .price-block .price-value {
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 32px;
      font-weight: 700;
      color: #0a1628;
    }

    .price-block.bid .price-value { color: var(--accent); }

    .price-arrow {
      font-size: 24px;
      color: #dde3ec;
      text-align: center;
    }

    .margin-pill {
      display: inline-block;
      background: rgba(45,198,83,0.12);
      color: var(--success);
      font-family: 'IBM Plex Mono', monospace;
      font-size: 13px;
      font-weight: 500;
      padding: 4px 10px;
      border-radius: 20px;
      margin-top: 4px;
    }
  </style>
</head>
<body>

  <!-- ── SIDEBAR ───────────────────────────────────────── -->
  <aside class="sidebar">
    <div class="sidebar-logo">
      <div class="app-name">⚡ Sales</div>
      <div class="app-sub">DIBBS · DLA Procurement</div>
    </div>

    <nav class="sidebar-nav">

      <div class="nav-section-label">Operations</div>
      <a href="/sales/" class="nav-item {% if request.resolver_match.url_name == 'dashboard' %}active{% endif %}">
        <span class="nav-icon">🏠</span> Dashboard
      </a>
      <a href="/sales/import/upload/" class="nav-item">
        <span class="nav-icon">📥</span> Daily Import
      </a>

      <div class="nav-section-label">Pipeline</div>
      <a href="/sales/solicitations/" class="nav-item">
        <span class="nav-icon">📋</span> Solicitations
        <span class="nav-badge warn">{{ pending_sol_count|default:'' }}</span>
      </a>
      <a href="/sales/rfq/pending/" class="nav-item">
        <span class="nav-icon">📨</span> RFQ Center
        <span class="nav-badge">{{ pending_rfq_count|default:'' }}</span>
      </a>
      <a href="/sales/bids/ready/" class="nav-item">
        <span class="nav-icon">💰</span> Bid Center
        <span class="nav-badge ok">{{ bids_ready_count|default:'' }}</span>
      </a>

      <div class="nav-section-label">Data</div>
      <a href="/sales/suppliers/" class="nav-item">
        <span class="nav-icon">🏭</span> Suppliers
      </a>

      <div class="nav-section-label">System</div>
      <a href="/sales/settings/cages/" class="nav-item">
        <span class="nav-icon">⚙️</span> Settings
      </a>

    </nav>

    <div class="sidebar-footer">
      <div class="user-chip">
        <div class="user-avatar">{{ request.user.first_name.0 }}{{ request.user.last_name.0 }}</div>
        <div>
          <div class="user-name">{{ request.user.get_full_name }}</div>
          <div class="user-role">Sales Staff</div>
        </div>
      </div>
    </div>
  </aside>

  <!-- ── MAIN ──────────────────────────────────────────── -->
  <div class="main">

    <div class="topbar">
      <div class="topbar-breadcrumb">
        {% block breadcrumb %}Sales{% endblock %}
      </div>
      <div class="topbar-actions">
        {% if latest_import_date %}
          <div class="import-date-chip">LAST IMPORT: {{ latest_import_date|date:"D M d" }}</div>
        {% endif %}
        <a href="/sales/import/upload/" class="btn btn-primary btn-sm">+ Import Files</a>
      </div>
    </div>

    <div class="page-body">
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-{% if message.tags == 'error' %}danger{% elif message.tags == 'warning' %}warn{% else %}ok{% endif %}">
            {{ message }}
          </div>
        {% endfor %}
      {% endif %}

      {% block content %}{% endblock %}
    </div>
  </div>

</body>
</html>
```

---

## 9.5 Dashboard — `/sales/`

The dashboard is the first thing users see. It answers three questions immediately: **What came in today? What needs attention right now? What's moving through the pipeline?**

```html
{% extends "sales/base.html" %}
{% block title %}Dashboard{% endblock %}
{% block breadcrumb %}Dashboard{% endblock %}

{% block content %}

<!-- Stat Strip -->
<div class="stat-grid">
  <div class="stat-card accent">
    <div class="stat-label">Today's Solicitations</div>
    <div class="stat-value">{{ today_count }}</div>
    <div class="stat-sub">imported {{ latest_import_date|timesince }} ago</div>
  </div>
  <div class="stat-card warn">
    <div class="stat-label">RFQs Pending Send</div>
    <div class="stat-value">{{ pending_rfq_count }}</div>
    <div class="stat-sub">awaiting your review</div>
  </div>
  <div class="stat-card danger">
    <div class="stat-label">Overdue Responses</div>
    <div class="stat-value">{{ overdue_count }}</div>
    <div class="stat-sub">return date &lt; 48 hrs</div>
  </div>
  <div class="stat-card success">
    <div class="stat-label">Ready to Bid</div>
    <div class="stat-value">{{ bids_ready_count }}</div>
    <div class="stat-sub">have supplier pricing</div>
  </div>
  <div class="stat-card navy">
    <div class="stat-label">Submitted Today</div>
    <div class="stat-value">{{ submitted_today }}</div>
    <div class="stat-sub">bids sent to DIBBS</div>
  </div>
</div>

<!-- Urgent Actions -->
{% if overdue_items %}
<div class="alert alert-danger">
  ⚠ {{ overdue_items|length }} solicitation{{ overdue_items|pluralize }} expire within 48 hours —
  <a href="/sales/solicitations/?filter=urgent" style="color:inherit;font-weight:600;">review now →</a>
</div>
{% endif %}

<div style="display:grid; grid-template-columns: 1fr 1fr; gap: 24px;">

  <!-- Recent Solicitations -->
  <div class="data-table-wrap">
    <div class="table-header">
      <div class="table-title">Recent Solicitations</div>
      <a href="/sales/solicitations/" class="btn btn-ghost btn-sm">View All</a>
    </div>
    <table>
      <thead>
        <tr>
          <th>Solicitation #</th>
          <th>Nomenclature</th>
          <th>Return By</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {% for sol in recent_solicitations %}
        <tr onclick="location.href='/sales/solicitations/{{ sol.solicitation_number }}/'">
          <td><span class="mono">{{ sol.solicitation_number }}</span></td>
          <td>{{ sol.lines.first.nomenclature|truncatechars:22 }}</td>
          <td>
            <span class="{% if sol.is_urgent %}badge badge-warn{% else %}mono{% endif %}">
              {{ sol.return_by_date|date:"M d" }}
            </span>
          </td>
          <td>
            <span class="badge badge-{{ sol.status|lower|slugify }}">{{ sol.get_status_display }}</span>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Pipeline Summary -->
  <div class="data-table-wrap">
    <div class="table-header">
      <div class="table-title">Pipeline Status</div>
    </div>
    <div style="padding: 20px;">
      {% for stage in pipeline_summary %}
      <div style="display:flex; align-items:center; justify-content:space-between;
                  padding: 10px 0; border-bottom: 1px solid #eef2f8;">
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="font-size:18px;">{{ stage.icon }}</span>
          <span style="font-size:13px; font-weight:500; color:#1a2940;">{{ stage.label }}</span>
        </div>
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="background:#eef2f8; border-radius:4px; height:6px; width:80px; overflow:hidden;">
            <div style="background:var(--accent); height:100%; width:{{ stage.pct }}%;"></div>
          </div>
          <span class="mono" style="font-size:13px; font-weight:600; color:#1a2940; min-width:28px; text-align:right;">
            {{ stage.count }}
          </span>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>

</div>
{% endblock %}
```

---

## 9.6 Solicitations List — `/sales/solicitations/`

The master list. Users filter down to what they need, then click through to the detail. The status badge is the primary visual language — a user can scan the list and know the state of every deal instantly.

```html
{% extends "sales/base.html" %}
{% block title %}Solicitations{% endblock %}
{% block breadcrumb %}Solicitations{% endblock %}

{% block content %}

<!-- Filter Bar -->
<div style="display:flex; align-items:center; gap:12px; margin-bottom:20px; flex-wrap:wrap;">
  <input type="text" class="search-input" placeholder="Search NSN, solicitation #, nomenclature..."
         hx-get="/sales/solicitations/" hx-trigger="keyup changed delay:300ms"
         hx-target="#sol-table-body" hx-include="[name='status'],[name='set_aside']"
         name="q" value="{{ request.GET.q }}">

  <select class="form-control" style="width:auto;" name="status"
          hx-get="/sales/solicitations/" hx-trigger="change"
          hx-target="#sol-table-body" hx-include="[name='q'],[name='set_aside']">
    <option value="">All Statuses</option>
    <option value="NEW">New</option>
    <option value="RFQ_PENDING">RFQ Pending</option>
    <option value="RFQ_SENT">RFQ Sent</option>
    <option value="BID_READY">Bid Ready</option>
    <option value="SUBMITTED">Submitted</option>
    <option value="NO_BID">No Bid</option>
  </select>

  <select class="form-control" style="width:auto;" name="set_aside">
    <option value="">All Set-Asides</option>
    <option value="N">Unrestricted</option>
    <option value="Y">Small Business</option>
    <option value="H">HUBZone</option>
    <option value="R">SDVOSB</option>
  </select>

  <div style="margin-left:auto; display:flex; gap:8px;">
    <a href="/sales/solicitations/nobid/" class="btn btn-ghost btn-sm">No-Bid Queue</a>
    <span style="font-family:'IBM Plex Mono',monospace; font-size:12px; color:#7a90b0;
                 align-self:center;">{{ total_count }} solicitations</span>
  </div>
</div>

<div class="data-table-wrap">
  <table>
    <thead>
      <tr>
        <th><input type="checkbox" id="select-all"></th>
        <th>Solicitation #</th>
        <th>NSN / Part #</th>
        <th>Nomenclature</th>
        <th>Qty</th>
        <th>UI</th>
        <th>Return By</th>
        <th>Set-Aside</th>
        <th>Status</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="sol-table-body">
      {% for sol in solicitations %}
      {% with line=sol.lines.first %}
      <tr onclick="location.href='/sales/solicitations/{{ sol.solicitation_number }}/'">
        <td onclick="event.stopPropagation()">
          <input type="checkbox" name="selected" value="{{ sol.id }}">
        </td>
        <td><span class="mono">{{ sol.solicitation_number }}</span></td>
        <td><span class="mono">{{ line.nsn }}</span></td>
        <td style="max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          {{ line.nomenclature }}
        </td>
        <td><span class="mono">{{ line.quantity }}</span></td>
        <td><span class="mono">{{ line.unit_of_issue }}</span></td>
        <td>
          {% if sol.days_remaining <= 2 %}
            <span class="badge badge-warn">{{ sol.return_by_date|date:"M d" }} ⚠</span>
          {% else %}
            <span class="mono">{{ sol.return_by_date|date:"M d" }}</span>
          {% endif %}
        </td>
        <td>
          {% if sol.small_business_set_aside != 'N' %}
            <span class="badge badge-sb">{{ sol.get_small_business_set_aside_display }}</span>
          {% else %}
            <span style="color:#c0ccd8; font-size:12px;">—</span>
          {% endif %}
        </td>
        <td>
          <span class="badge badge-{{ sol.status|lower|cut:'_' }}">{{ sol.get_status_display }}</span>
        </td>
        <td onclick="event.stopPropagation()">
          <a href="/sales/solicitations/{{ sol.solicitation_number }}/"
             class="btn btn-ghost btn-sm">Open →</a>
        </td>
      </tr>
      {% endwith %}
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

---

## 9.7 Solicitation Detail — `/sales/solicitations/<sol#>/`

The command center for a single deal. The pipeline track at the top tells you exactly where this solicitation is. Five tabs break the work into logical stages so nothing gets missed.

**Cost of Money Calculator:** a Bootstrap modal (`#costOfMoneyModal`) triggered from the **Sales primary nav** (**💰 Cost of Money**, right side) on any page under `/sales/solicitations/…` (list, workbench, closed, mass pass, review queues, etc.). Markup and script live in `sales/base.html`; `solicitation_nav_tools` sets visibility. Calculates carry cost using `COST_OF_MONEY_DAILY_RATE` (defined in `sales/views/solicitations.py`, default `0.000329` ≈ 12% annual). Front-end only — no model, no URL, no persistence.

**Matches tab**

- **Manual supplier add (workbench sidebar)** — HTMX typeahead on **Add supplier manually**: `hx-get` to `rfq_manual_supplier_search` with debounced `keyup` (300ms), `?q=` plus `solicitation_number` to exclude suppliers who already have a `SupplierRFQ` on this solicitation. JSON API (non-HTMX) returns `[{id, name, cage}]`. Choosing a row `POST`s `rfq_queue_add_manual` (`supplier_id`, `solicitation_number` or `sol_number`): creates `SupplierRFQ(status='QUEUED', sent_by=user)` only — **no** `SupplierMatch` at queue time; `SupplierMatch(match_method='MANUAL', match_tier=3, match_score=0)` is created when a quote is saved in `rfq_enter_quote` if still missing. No Quote CAGE → JSON `409` / HTMX inline error **No Quote CAGE**. Success refreshes `#wb-matches-sidebar` via out-of-band swap. Sidebar rows show a **Manual** badge for manual-queue or MANUAL-match suppliers and an **In Queue** pill when `QUEUED`.

- **Matched & approved sources (sidebar)** — Rows without a `suppliers.Supplier` match show a **Look Up** link that opens **`/sales/entity/cage/<CAGE>/`** in a **new browser tab** (full-page SAM entity lookup; cache-first via `get_or_fetch_cage` / `SAMEntityCache` on that page; **Last verified … ↻** on the entity page). For display **only** (no API call in the workbench view), if a prior visit to the entity page filled `SAMEntityCache` (`fetch_error=False`), the **Supplier** column shows **`entity_name`** with a muted **SAM** badge (tooltip: name from SAM.gov, not in supplier DB); otherwise an em dash until the user opens **Look Up** at least once.

```html
{% extends "sales/base.html" %}
{% block title %}{{ solicitation.solicitation_number }}{% endblock %}
{% block breadcrumb %}
  <a href="/sales/solicitations/" style="color:#7a90b0;text-decoration:none;">Solicitations</a>
  <span class="crumb-sep">/</span>
  <span class="mono">{{ solicitation.solicitation_number }}</span>
{% endblock %}

{% block content %}

<!-- Pipeline Track — the signature UI element -->
<div class="pipeline-track">
  {% for step in pipeline_steps %}
  <div class="pipeline-step {{ step.state }}">
    <span class="step-icon">{{ step.icon }}</span>
    <div class="step-label">{{ step.label }}</div>
  </div>
  {% endfor %}
</div>

<!-- Header Card -->
<div style="display:grid; grid-template-columns: 1fr auto; gap: 24px; margin-bottom: 24px; align-items:start;">
  <div class="form-card" style="margin-bottom:0;">
    <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:16px;">
      <div>
        <div class="form-label">Solicitation #</div>
        <div class="mono" style="font-size:15px; font-weight:600; color:#0a1628; margin-top:4px;">
          {{ solicitation.solicitation_number }}
        </div>
      </div>
      <div>
        <div class="form-label">NSN</div>
        <div class="mono" style="font-size:15px; font-weight:600; color:#0a1628; margin-top:4px;">
          {{ line.nsn }}
        </div>
      </div>
      <div>
        <div class="form-label">Nomenclature</div>
        <div style="font-size:14px; font-weight:500; color:#1a2940; margin-top:4px;">
          {{ line.nomenclature }}
        </div>
      </div>
      <div>
        <div class="form-label">Return By</div>
        <div style="margin-top:4px;">
          {% if solicitation.days_remaining <= 2 %}
            <span class="badge badge-warn" style="font-size:13px;">
              {{ solicitation.return_by_date|date:"N j, Y" }} — {{ solicitation.days_remaining }}d left ⚠
            </span>
          {% else %}
            <span style="font-size:14px; font-weight:500; color:#1a2940;">
              {{ solicitation.return_by_date|date:"N j, Y" }}
            </span>
            <span style="font-size:12px; color:#7a90b0; display:block;">{{ solicitation.days_remaining }} days remaining</span>
          {% endif %}
        </div>
      </div>
      <div>
        <div class="form-label">Qty / UI</div>
        <div class="mono" style="font-size:14px; font-weight:600; margin-top:4px;">
          {{ line.quantity }} {{ line.unit_of_issue }}
        </div>
      </div>
      <div>
        <div class="form-label">Set-Aside</div>
        <div style="margin-top:4px;">
          {% if solicitation.small_business_set_aside != 'N' %}
            <span class="badge badge-sb">{{ solicitation.get_small_business_set_aside_display }}</span>
          {% else %}
            <span style="font-size:13px; color:#7a90b0;">Unrestricted</span>
          {% endif %}
        </div>
      </div>
      <div>
        <div class="form-label">Solicitation Type</div>
        <div class="mono" style="font-size:13px; margin-top:4px;">
          {{ solicitation.get_solicitation_type_display|default:"Standard" }}
        </div>
      </div>
      <div>
        <div class="form-label">PDF</div>
        <div style="margin-top:4px;">
          <a href="{{ pdf_url }}" target="_blank" class="btn btn-ghost btn-sm">📄 View RFQ</a>
        </div>
      </div>
    </div>
  </div>

  <!-- Quick Actions -->
  <div style="display:flex; flex-direction:column; gap:8px; min-width:160px;">
    {% if solicitation.status == 'RFQ_PENDING' %}
      <a href="/sales/rfq/pending/?sol={{ solicitation.solicitation_number }}"
         class="btn btn-primary">📨 Review & Send RFQs</a>
    {% endif %}
    {% if solicitation.status == 'BID_READY' %}
      <a href="/sales/bids/{{ solicitation.solicitation_number }}/build/"
         class="btn btn-primary">💰 Build Bid</a>
    {% endif %}
    {% if solicitation.status == 'DRAFT' %}
      <a href="/sales/bids/export/?sol={{ solicitation.solicitation_number }}"
         class="btn btn-success">⬆ Export BQ File</a>
    {% endif %}
    <form method="post" action="/sales/solicitations/{{ solicitation.solicitation_number }}/nobid/">
      {% csrf_token %}
      <button type="submit" class="btn btn-ghost btn-sm" style="width:100%;">✗ Mark No-Bid</button>
    </form>
  </div>
</div>

<!-- Tab Bar -->
<div class="tab-bar">
  <a href="?tab=overview"  class="tab-item {% if active_tab == 'overview'  %}active{% endif %}">
    📋 Overview
  </a>
  <a href="?tab=matches"   class="tab-item {% if active_tab == 'matches'   %}active{% endif %}">
    🎯 Matches <span class="tab-count">{{ match_count }}</span>
  </a>
  <a href="?tab=rfqs"      class="tab-item {% if active_tab == 'rfqs'      %}active{% endif %}">
    📨 RFQs <span class="tab-count">{{ rfq_count }}</span>
  </a>
  <a href="?tab=quotes"    class="tab-item {% if active_tab == 'quotes'    %}active{% endif %}">
    💬 Quotes <span class="tab-count">{{ quote_count }}</span>
  </a>
  <a href="?tab=bid"       class="tab-item {% if active_tab == 'bid'       %}active{% endif %}">
    💰 Bid
  </a>
</div>

<!-- ── MATCHES TAB ─────────────────────────────────── -->
{% if active_tab == 'matches' %}
{% if not match_count %}
  <div class="alert alert-info">No supplier matches found for this NSN. You can manually add a supplier or mark as No-Bid.</div>
{% else %}
<div class="data-table-wrap">
  <div class="table-header">
    <div class="table-title">Matched Suppliers</div>
    <form method="post" action="/sales/rfq/send-batch/">
      {% csrf_token %}
      <input type="hidden" name="solicitation" value="{{ solicitation.solicitation_number }}">
      <button type="submit" class="btn btn-primary btn-sm">📨 Send All RFQs</button>
    </form>
  </div>
  <table>
    <thead>
      <tr>
        <th><input type="checkbox"></th>
        <th>Supplier</th>
        <th>CAGE</th>
        <th>Match Method</th>
        <th>Status Flags</th>
        <th>Contact Email</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>
      {% for match in matches %}
      <tr>
        <td><input type="checkbox" {% if match.is_excluded %}disabled{% endif %}></td>
        <td>
          <a href="/sales/suppliers/{{ match.supplier.id }}/"
             style="font-weight:600; color:#1a2940; text-decoration:none;">
            {{ match.supplier.name }}
          </a>
        </td>
        <td><span class="mono">{{ match.supplier.cage_code }}</span></td>
        <td>
          <span class="badge badge-tier{{ match.match_tier }}">
            T{{ match.match_tier }} · {{ match.get_match_method_display }}
          </span>
        </td>
        <td>
          {% if match.supplier.probation %}
            <span class="badge badge-warn">⚠ Probation</span>
          {% elif match.supplier.conditional %}
            <span class="badge badge-rfq-pend">⚠ Conditional</span>
          {% else %}
            <span style="color:#2dc653; font-size:12px;">✓ Clear</span>
          {% endif %}
        </td>
        <td>
          <span class="mono" style="font-size:11px; color:#5a7090;">
            {{ match.supplier.primary_email|default:match.supplier.business_email|default:"—" }}
          </span>
        </td>
        <td>
          {% if not match.is_excluded %}
            <form method="post" action="/sales/rfq/send/" style="display:inline;">
              {% csrf_token %}
              <input type="hidden" name="match_id" value="{{ match.id }}">
              <button type="submit" class="btn btn-primary btn-sm">Send RFQ</button>
            </form>
          {% else %}
            <span style="color:#a0aec0; font-size:12px;">Excluded</span>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}
{% endif %}

<!-- ── QUOTES TAB ──────────────────────────────────── -->
{% if active_tab == 'quotes' %}
{% if not quote_count %}
  <div class="alert alert-info">No supplier quotes received yet. Send RFQs from the Matches tab and enter responses when suppliers reply.</div>
{% else %}
<div class="data-table-wrap">
  <div class="table-header">
    <div class="table-title">Supplier Quotes</div>
  </div>
  <table>
    <thead>
      <tr>
        <th>Supplier</th>
        <th>Part # Offered</th>
        <th>Unit Price</th>
        <th>Lead Time</th>
        <th>Qty Available</th>
        <th>Suggested Bid</th>
        <th>Margin</th>
        <th>Action</th>
      </tr>
    </thead>
    <tbody>
      {% for quote in quotes %}
      <tr {% if quote.is_selected_for_bid %}style="background:rgba(45,198,83,0.05); outline:2px solid rgba(45,198,83,0.2);"{% endif %}>
        <td style="font-weight:600;">{{ quote.supplier.name }}</td>
        <td><span class="mono">{{ quote.part_number_offered|default:"—" }}</span></td>
        <td><span class="mono" style="font-weight:600; font-size:14px;">${{ quote.unit_price }}</span></td>
        <td><span class="mono">{{ quote.lead_time_days }}d</span></td>
        <td><span class="mono">{{ quote.quantity_available|default:"—" }}</span></td>
        <td>
          <span class="mono" style="color:var(--accent); font-weight:600;">
            ${{ quote.suggested_bid_price }}
          </span>
        </td>
        <td>
          <span class="margin-pill">{{ quote.default_margin_pct }}%</span>
        </td>
        <td>
          {% if not quote.is_selected_for_bid %}
            <form method="post" action="/sales/bids/select-quote/">
              {% csrf_token %}
              <input type="hidden" name="quote_id" value="{{ quote.id }}">
              <button type="submit" class="btn btn-success btn-sm">✓ Use This</button>
            </form>
          {% else %}
            <span style="color:var(--success); font-size:12px; font-weight:600;">✓ Selected</span>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}
{% endif %}

{% endblock %}
```

---

## 9.8 Bid Builder — `/sales/bids/<sol#>/build/`

The most complex screen in the app. Broken into collapsible sections so it doesn't overwhelm. The price comparison card at the top anchors the user — they always know where their margin stands.

#### Price Anchor Card — Last Award Reference

The Price Anchor card shows three columns:

| Supplier Cost | Last Award Price | Your Bid Price |
|---|---|---|
| From selected quote | Most recent DibbsAward for this NSN | Editable, live margin |

**Last Award block** shows: contract price, awardee CAGE, award date.
If no award data exists for the NSN, the block renders as "—" (placeholder, no data).

**Orange warning badge** ("⚠ Bid Above Last Award") appears on page load when
`suggested_bid_price > last_award.total_contract_price`. Passive — does not block saving.

**See History link** opens a modal with up to 5 most recent `DibbsAward` records for the
NSN, ordered by `award_date` descending. Modal footer links to the full Awards list filtered
by that NSN.

**NSN matching:** `line.nsn` hyphens are stripped before querying `DibbsAward.nsn` to
handle format differences between DIBBS solicitation files and AW files.

```html
{% extends "sales/base.html" %}
{% block title %}Build Bid — {{ solicitation.solicitation_number }}{% endblock %}
{% block breadcrumb %}
  <a href="/sales/bids/ready/" style="color:#7a90b0;text-decoration:none;">Bid Center</a>
  <span class="crumb-sep">/</span>
  Build Bid
  <span class="crumb-sep">/</span>
  <span class="mono">{{ solicitation.solicitation_number }}</span>
{% endblock %}

{% block content %}

<!-- Price Anchoring Card -->
<div class="price-compare">
  <div class="price-block">
    <div class="price-label">Supplier Cost</div>
    <div class="price-value">${{ selected_quote.unit_price }}</div>
    <div style="font-size:12px; color:#7a90b0; margin-top:4px;">{{ selected_quote.supplier.name }}</div>
  </div>
  <div class="price-arrow">→</div>
  <div class="price-block bid">
    <div class="price-label">Your Bid Price</div>
    <div class="price-value" id="live-bid-price">${{ suggested_bid_price }}</div>
    <div class="margin-pill" id="live-margin">{{ default_margin_pct }}% margin</div>
  </div>
</div>

<form method="post" action="/sales/bids/{{ solicitation.solicitation_number }}/build/">
{% csrf_token %}

<!-- Section 1: Identity -->
<div class="form-card">
  <div class="form-section-title">01 · Quote Identity</div>
  <div class="form-grid">
    <div class="form-group">
      <label class="form-label">Quoter CAGE <span style="color:var(--danger)">*</span></label>
      <select name="quoter_cage" class="form-control" required>
        {% for cage in company_cages %}
          <option value="{{ cage.cage_code }}" {% if cage.is_default %}selected{% endif %}>
            {{ cage.cage_code }} — {{ cage.company_name }}
          </option>
        {% endfor %}
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Quote For CAGE <span style="color:var(--danger)">*</span></label>
      <select name="quote_for_cage" class="form-control" required>
        {% for cage in company_cages %}
          <option value="{{ cage.cage_code }}" {% if cage.is_default %}selected{% endif %}>
            {{ cage.cage_code }} — {{ cage.company_name }}
          </option>
        {% endfor %}
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Bid Type <span style="color:var(--danger)">*</span></label>
      <select name="bid_type_code" class="form-control" required>
        <option value="BI" selected>BI — Bid Without Exception</option>
        <option value="BW">BW — Bid With Exception</option>
        <option value="AB">AB — Alternate Bid</option>
        <option value="DQ">DQ — No Bid</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Solicitation # (read-only)</label>
      <input class="form-control" value="{{ solicitation.solicitation_number }}" readonly>
    </div>
  </div>
</div>

<!-- Section 2: Pricing & Delivery -->
<div class="form-card">
  <div class="form-section-title">02 · Pricing & Delivery</div>
  <div class="form-grid">
    <div class="form-group">
      <label class="form-label">Unit Price <span style="color:var(--danger)">*</span></label>
      <input type="number" name="unit_price" class="form-control price-field"
             step="0.00001" min="0" required
             value="{{ suggested_bid_price }}"
             id="unit-price-input"
             oninput="updateMargin(this.value)">
      <div class="form-hint">Supplier cost: ${{ selected_quote.unit_price }} · Default markup: {{ default_cage.default_markup_pct }}%</div>
    </div>
    <div class="form-group">
      <label class="form-label">Delivery Days <span style="color:var(--danger)">*</span></label>
      <input type="number" name="delivery_days" class="form-control"
             min="0" max="9999" required
             value="{{ suggested_delivery_days }}"
             placeholder="{{ line.delivery_days }}">
      <div class="form-hint">RFQ requires {{ line.delivery_days }} days</div>
    </div>
    <div class="form-group">
      <label class="form-label">FOB Point</label>
      <select name="fob_point" class="form-control">
        <option value="D" selected>D — Destination</option>
        <option value="O">O — Origin</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Payment Terms</label>
      <select name="payment_terms" class="form-control">
        <option value="1" selected>Net 30</option>
        <option value="10">2% 10 Days</option>
        <option value="3">½% 20 Days</option>
      </select>
    </div>
  </div>
</div>

<!-- Section 3: Supply Source -->
<div class="form-card">
  <div class="form-section-title">03 · Supply Source</div>
  <div class="form-grid">
    <div class="form-group">
      <label class="form-label">Manufacturer / Dealer <span style="color:var(--danger)">*</span></label>
      <select name="manufacturer_dealer" class="form-control" required
              onchange="toggleMfgCage(this.value)">
        <option value="MM">MM — Manufacturer</option>
        <option value="DD" selected>DD — Dealer</option>
        <option value="QM">QM — QPL Manufacturer</option>
        <option value="QD">QD — QPL Dealer</option>
      </select>
    </div>
    <div class="form-group" id="mfg-cage-group">
      <label class="form-label">Actual Mfg CAGE <span style="color:var(--danger)">*</span></label>
      <input type="text" name="mfg_source_cage" class="form-control mono"
             maxlength="5" placeholder="5-char CAGE"
             value="{{ selected_quote.supplier.cage_code }}">
      <div class="form-hint">Required when Dealer or QPL Dealer</div>
    </div>
    <div class="form-group">
      <label class="form-label">Material Requirements</label>
      <select name="material_requirements" class="form-control">
        <option value="0" selected>0 — New</option>
        <option value="1">1 — Other Than New (Used)</option>
        <option value="2">2 — Reconditioned</option>
        <option value="3">3 — Remanufactured</option>
        <option value="4">4 — Unused Former Gov't Surplus</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Hazardous Material</label>
      <select name="hazardous_material" class="form-control">
        <option value="N" selected>N — No</option>
        <option value="Y">Y — Yes</option>
      </select>
    </div>
  </div>
</div>

<!-- Section 4: Part Number (conditional on item desc indicator) -->
{% if line.item_description_indicator in 'PBN' %}
<div class="form-card">
  <div class="form-section-title">04 · Part Number Offered</div>
  <div class="form-grid">
    <div class="form-group">
      <label class="form-label">Part Number Code <span style="color:var(--danger)">*</span></label>
      <select name="part_number_offered_code" class="form-control" required>
        <option value="1">1 — Exact Product</option>
        <option value="2">2 — Alternate Product</option>
        <option value="3">3 — Superseding P/N (Admin Change)</option>
        <option value="5">5 — Previously-Approved Product</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">CAGE of Part Offered <span style="color:var(--danger)">*</span></label>
      <input type="text" name="part_number_offered_cage" class="form-control mono"
             maxlength="5" value="{{ approved_sources.0.approved_cage|default:'' }}">
    </div>
    <div class="form-group" style="grid-column: span 2;">
      <label class="form-label">Part Number <span style="color:var(--danger)">*</span></label>
      <input type="text" name="part_number_offered" class="form-control mono"
             maxlength="40" value="{{ approved_sources.0.part_number|default:'' }}">
    </div>
  </div>
</div>
{% endif %}

<!-- Section 5: Compliance (pre-filled from CAGE defaults, read-only review) -->
<div class="form-card">
  <div class="form-section-title">05 · Compliance Representations
    <span style="font-size:11px; font-weight:400; color:#7a90b0; text-transform:none; margin-left:8px;">
      Pre-filled from CAGE settings — review only
    </span>
  </div>
  <div class="form-grid">
    <div class="form-group">
      <label class="form-label">SB Representations (col 13)</label>
      <input class="form-control mono" value="{{ active_cage.sb_representations_code }}" readonly
             style="background:#f0f0f0; color:#5a7090;">
    </div>
    <div class="form-group">
      <label class="form-label">Affirmative Action (col 21)</label>
      <input class="form-control mono" value="{{ active_cage.affirmative_action_code }}" readonly
             style="background:#f0f0f0; color:#5a7090;">
    </div>
    <div class="form-group">
      <label class="form-label">Previous Contracts (col 22)</label>
      <input class="form-control mono" value="{{ active_cage.previous_contracts_code }}" readonly
             style="background:#f0f0f0; color:#5a7090;">
    </div>
    <div class="form-group">
      <label class="form-label">Child Labor (col 120)</label>
      <input class="form-control mono" value="{{ active_cage.default_child_labor_code }}" readonly
             style="background:#f0f0f0; color:#5a7090;">
    </div>
  </div>
</div>

<!-- Remarks (only shown when bid type is BW or AB) -->
<div class="form-card" id="remarks-card" style="display:none;">
  <div class="form-section-title">06 · Quote Remarks (col 121)</div>
  <div class="form-group">
    <label class="form-label">Remarks</label>
    <textarea name="bid_remarks" class="form-control" rows="3" maxlength="255"
              placeholder="Required for BW and AB bids — explain the exception..."></textarea>
    <div class="form-hint">Max 255 characters · Not allowed on BI (Bid Without Exception) bids</div>
  </div>
</div>

<!-- Submit -->
<div style="display:flex; gap:12px; justify-content:flex-end; padding-top:8px;">
  <a href="/sales/solicitations/{{ solicitation.solicitation_number }}/?tab=bid"
     class="btn btn-ghost">Cancel</a>
  <button type="submit" name="action" value="save_draft" class="btn btn-navy">
    💾 Save Draft
  </button>
  <button type="submit" name="action" value="mark_ready" class="btn btn-success">
    ✓ Mark Ready to Export
  </button>
</div>

</form>

<script>
  const supplierCost = {{ selected_quote.unit_price|floatformat:5 }};

  function updateMargin(bidPrice) {
    const price = parseFloat(bidPrice);
    if (!price || !supplierCost) return;
    const margin = ((price - supplierCost) / price * 100).toFixed(1);
    document.getElementById('live-bid-price').textContent = '$' + parseFloat(bidPrice).toFixed(5);
    document.getElementById('live-margin').textContent = margin + '% margin';
    document.getElementById('live-margin').style.background =
      margin < 0 ? 'rgba(230,57,70,0.15)' :
      margin < 2 ? 'rgba(244,162,97,0.15)' : 'rgba(45,198,83,0.12)';
    document.getElementById('live-margin').style.color =
      margin < 0 ? 'var(--danger)' :
      margin < 2 ? 'var(--accent-warm)' : 'var(--success)';
  }

  function toggleMfgCage(val) {
    const group = document.getElementById('mfg-cage-group');
    group.style.display = ['DD','QD'].includes(val) ? 'flex' : 'none';
  }

  document.querySelector('[name="bid_type_code"]').addEventListener('change', function() {
    document.getElementById('remarks-card').style.display =
      ['BW','AB'].includes(this.value) ? 'block' : 'none';
  });
</script>
{% endblock %}
```

---

## 9.9 Daily Import — `/sales/import/upload/`

A clean, reassuring upload screen. The three files go in together. Filename validation happens immediately on drop so users know before they commit.

```html
{% extends "sales/base.html" %}
{% block title %}Daily Import{% endblock %}
{% block breadcrumb %}Daily Import{% endblock %}

{% block content %}

{% if import_preview %}
<!-- Step 2: Preview before commit -->
<div class="alert alert-info">
  ℹ Files parsed successfully. Review the counts below and click Confirm Import to load into the database.
</div>

<div class="stat-grid" style="grid-template-columns: repeat(4, 1fr);">
  <div class="stat-card accent">
    <div class="stat-label">Import Date</div>
    <div class="stat-value" style="font-size:24px;">{{ import_preview.date|date:"M d" }}</div>
    <div class="stat-sub">{{ import_preview.date|date:"Y" }}</div>
  </div>
  <div class="stat-card navy">
    <div class="stat-label">Solicitations (IN)</div>
    <div class="stat-value">{{ import_preview.solicitation_count }}</div>
  </div>
  <div class="stat-card navy">
    <div class="stat-label">Quote Lines (BQ)</div>
    <div class="stat-value">{{ import_preview.bq_count }}</div>
  </div>
  <div class="stat-card navy">
    <div class="stat-label">Approved Sources (AS)</div>
    <div class="stat-value">{{ import_preview.as_count }}</div>
  </div>
</div>

{% if import_preview.warnings %}
<div class="alert alert-warn">
  ⚠ {{ import_preview.warnings|length }} warning(s) found — import will still proceed but review after:
  <ul style="margin-top:8px; padding-left:20px;">
    {% for w in import_preview.warnings %}<li>{{ w }}</li>{% endfor %}
  </ul>
</div>
{% endif %}

<div style="display:flex; gap:12px; justify-content:flex-end;">
  <a href="/sales/import/upload/" class="btn btn-ghost">← Start Over</a>
  <form method="post" action="/sales/import/confirm/">
    {% csrf_token %}
    <input type="hidden" name="batch_id" value="{{ import_preview.batch_id }}">
    <button type="submit" class="btn btn-primary" style="font-size:15px; padding:10px 24px;">
      ✓ Confirm Import — {{ import_preview.solicitation_count }} Solicitations
    </button>
  </form>
</div>

{% else %}
<!-- Step 1: File Upload -->
<div style="max-width: 680px; margin: 0 auto;">

  <div style="text-align:center; margin-bottom:32px;">
    <div style="font-family:'Barlow Condensed',sans-serif; font-size:28px; font-weight:700;
                color:#0a1628; margin-bottom:8px;">Upload Today's DIBBS Files</div>
    <div style="font-size:14px; color:#7a90b0;">
      Download IN, BQ, and AS files from DIBBS for the same date, then drop them all here together.
    </div>
  </div>

  <form method="post" enctype="multipart/form-data" action="/sales/import/upload/"
        id="upload-form">
    {% csrf_token %}

    <div id="drop-zone"
         style="border: 2px dashed #c8d3e0; border-radius:12px; padding:48px 32px;
                text-align:center; background:#f7f9fc; transition:all 0.2s; cursor:pointer;
                margin-bottom:24px;"
         ondragover="event.preventDefault(); this.style.borderColor='var(--accent)'; this.style.background='#f0faff';"
         ondragleave="this.style.borderColor='#c8d3e0'; this.style.background='#f7f9fc';"
         ondrop="handleDrop(event)">
      <div style="font-size:48px; margin-bottom:12px;">📁</div>
      <div style="font-family:'Barlow Condensed',sans-serif; font-size:20px; font-weight:600;
                  color:#1a2940; margin-bottom:6px;">Drop all three files here</div>
      <div style="font-size:13px; color:#7a90b0; margin-bottom:20px;">
        or click to browse
      </div>
      <input type="file" id="file-input" name="files" multiple accept=".txt"
             style="display:none;" onchange="handleFiles(this.files)">
      <button type="button" onclick="document.getElementById('file-input').click()"
              class="btn btn-ghost">Browse Files</button>
    </div>

    <!-- File Validation Status -->
    <div id="file-status" style="display:none; margin-bottom:24px;">
      <div class="form-card" style="padding:16px;">
        <div class="form-section-title" style="margin-bottom:12px;">File Check</div>
        <div id="in-file-status"  class="file-row"></div>
        <div id="bq-file-status"  class="file-row"></div>
        <div id="as-file-status"  class="file-row"></div>
        <div id="date-match-status" class="file-row"></div>
      </div>
    </div>

    <div id="submit-area" style="display:none; text-align:center;">
      <button type="submit" class="btn btn-primary" style="font-size:15px; padding:12px 32px;">
        📥 Parse & Preview Import
      </button>
    </div>
  </form>

  <!-- Expected format reminder -->
  <div style="background:#f0f4f8; border-radius:8px; padding:16px 20px; margin-top:24px;">
    <div style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:#5a7090;
                letter-spacing:0.06em; text-transform:uppercase; margin-bottom:10px;">
      Expected Filenames
    </div>
    <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:8px;">
      <div style="font-family:'IBM Plex Mono',monospace; font-size:12px;">
        <span style="color:var(--accent);">in</span><span style="color:#7a90b0;">YYMMDD</span><span style="color:#1a2940;">.txt</span>
        <div style="font-size:10px; color:#a0aec0; margin-top:2px;">Solicitation Index</div>
      </div>
      <div style="font-family:'IBM Plex Mono',monospace; font-size:12px;">
        <span style="color:var(--accent);">bq</span><span style="color:#7a90b0;">YYMMDD</span><span style="color:#1a2940;">.txt</span>
        <div style="font-size:10px; color:#a0aec0; margin-top:2px;">Batch Quote Template</div>
      </div>
      <div style="font-family:'IBM Plex Mono',monospace; font-size:12px;">
        <span style="color:var(--accent);">as</span><span style="color:#7a90b0;">YYMMDD</span><span style="color:#1a2940;">.txt</span>
        <div style="font-size:10px; color:#a0aec0; margin-top:2px;">Approved Sources</div>
      </div>
    </div>
  </div>

</div>
{% endif %}

<style>
  .file-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid #eef2f8;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
  }
  .file-row:last-child { border-bottom: none; }
  .file-row .file-icon { font-size: 16px; }
  .file-row .file-name { flex: 1; color: #1a2940; }
  .file-row .file-check { font-size: 14px; }
  .check-ok   { color: var(--success); }
  .check-fail { color: var(--danger); }
  .check-warn { color: var(--accent-warm); }
</style>

<script>
  function handleDrop(e) {
    e.preventDefault();
    e.currentTarget.style.borderColor = '#c8d3e0';
    e.currentTarget.style.background = '#f7f9fc';
    handleFiles(e.dataTransfer.files);
  }

  function handleFiles(files) {
    const fileArr = Array.from(files);
    const status = document.getElementById('file-status');
    status.style.display = 'block';

    const patterns = {
      in: /^in\d{6}\.txt$/i,
      bq: /^bq\d{6}\.txt$/i,
      as: /^as\d{6}\.txt$/i
    };

    let found = { in: null, bq: null, as: null };
    fileArr.forEach(f => {
      if (patterns.in.test(f.name)) found.in = f;
      if (patterns.bq.test(f.name)) found.bq = f;
      if (patterns.as.test(f.name)) found.as = f;
    });

    function row(type, label) {
      const f = found[type];
      const ok = !!f;
      document.getElementById(type + '-file-status').innerHTML =
        `<span class="file-icon">📄</span>
         <span class="file-name">${ok ? f.name : label + ' — NOT FOUND'}</span>
         <span class="file-check ${ok ? 'check-ok' : 'check-fail'}">${ok ? '✓' : '✗'}</span>`;
    }

    row('in', 'inYYMMDD.txt');
    row('bq', 'bqYYMMDD.txt');
    row('as', 'asYYMMDD.txt');

    // Date match check
    const dates = Object.values(found).filter(Boolean).map(f => f.name.slice(2,8));
    const allMatch = dates.length === 3 && new Set(dates).size === 1;
    document.getElementById('date-match-status').innerHTML =
      `<span class="file-icon">📅</span>
       <span class="file-name">Date consistency (${dates[0]||'?'}) — all three files same date</span>
       <span class="file-check ${allMatch ? 'check-ok' : 'check-fail'}">${allMatch ? '✓' : '✗'}</span>`;

    const allGood = found.in && found.bq && found.as && allMatch;
    const submitArea = document.getElementById('submit-area');
    submitArea.style.display = allGood ? 'block' : 'none';

    // Transfer files to the actual form input
    if (allGood) {
      const dt = new DataTransfer();
      Object.values(found).forEach(f => dt.items.add(f));
      document.getElementById('file-input').files = dt.files;
    }
  }
</script>

{% endblock %}
```


---

## 9.10 No Quote CAGE List

### Purpose
Sales team members can flag CAGE codes that have declined to work with the company. Flagged CAGEs are surfaced with a red "⛔ No Quote" badge on the solicitation detail page (both **Matches** tab and **Approved Sources** tables, including Overview approved sources) so the team can see risk without hiding matches.

### Data Model — `NoQuoteCAGE` (table: `dibbs_no_quote_cage`)
| Field | Type | Notes |
|---|---|---|
| `cage_code` | CharField(5) | Five-character CAGE; indexed |
| `reason` | TextField | Optional notes |
| `date_added` | DateField | Auto-set on creation |
| `added_by` | FK → User | SET_NULL on user deletion |
| `is_active` | BooleanField | True = currently flagged |
| `deactivated_at` | DateField | Set when restored; null if still active |

A partial unique constraint prevents duplicate **active** records for the same CAGE; multiple inactive rows preserve history.

### Adding a CAGE to the No Quote List
- **From supplier profile** (`/sales/suppliers/<id>/`): "Flag as No Quote" button → modal with optional reason → POST to `sales:supplier_no_quote_add` (uses `suppliers.Supplier.cage_code`, normalized).
- **From SAM entity lookup** (`/sales/entity/cage/<cage_code>/`): Same button and modal flow → POST to `sales:entity_no_quote_add`.

### Restoring a CAGE (removing from list)
From the Settings No Quote list page (`/sales/settings/no-quote/`, staff-only): **Restore** sets `is_active=False` and records `deactivated_at`. History is preserved in an expandable section.

### UI Behavior
- Matched suppliers with a No Quote CAGE show a red **"⛔ No Quote"** badge in the Matches tab. **+ Add to Queue** becomes **"⛔ Send Anyway"** and opens a confirmation modal; the confirmed action POSTs `force_no_quote=1` to `rfq_queue_add`.
- **Send All RFQs** / **Send Selected RFQs** on RFQ Pending (`rfq_send_batch`) **skip** No Quote CAGEs. **Send All** / multi-select send on the RFQ Queue page (`rfq_queue_send`) also skips them.
- Approved source rows (matched or not) show the badge when the AS CAGE is flagged; **Add & Queue** for not-in-system sources uses a confirmation modal and `supplier_create_and_queue` with `force_no_quote=1` when confirmed.
- `get_no_quote_cage_set()` in `sales/services/no_quote.py` loads active CAGEs once per solicitation detail / pending page render.

---

## 10. Email Workflow — Supplier Communication

### 10.1 The Core Problem

The sales team's primary daily work is a translation job: they send structured RFQ requests out, and they receive back a completely unstructured stream of supplier responses — emails with inline pricing, PDF attachments, phone calls followed by a voicemail, faxes, even text messages. No two suppliers respond the same way.

The app cannot control how suppliers reply. What it **can** do is make the translation from "supplier said X" into "structured quote record" as fast and frictionless as possible. This is where the sales team will spend the majority of their time, so every second of friction here is a second that costs money.

**Design principle: The app meets the salesperson where they are.** They are in their email client reading a supplier reply. The app should be one click away from recording that response, with as many fields pre-filled as possible, and as few required fields as possible to get the quote captured.

---

### 10.2 Outbound RFQ Email Flow

```
Sales team clicks "Send RFQ" for a matched supplier
        │
        ▼
System generates email from template (CAGE defaults pre-filled)
 - Subject: "RFQ: SPE1C126T0694 — BAG, DUFFEL — Return by Mar 19"
 - Body:    Full structured RFQ with NSN, qty, required delivery,
            return-by date, part number if known, PDF attachment link
        │
        ▼
Email sent via Django send_mail() to supplier's contact email
(priority: contact.email → primary_email → business_email)
        │
        ▼
dibbs_supplier_rfq record created with status=SENT, sent_at=now,
email_sent_to=snapshot of address used
        │
        ▼
Solicitation status advances to RFQ_SENT
```

**What goes in the RFQ email:**
- Solicitation number and line number
- NSN and nomenclature
- Required quantity and unit of issue
- Required delivery days
- Return-by date (hard deadline)
- Approved source CAGE(s) and part numbers if known
- Set-aside requirement (SB, HUBZone, etc.) if applicable
- Our CAGE and company name (so they know who to reply to)
- Direct "reply to this email" instruction
- Optional: direct link to the DIBBS PDF if accessible

**Email reply-to address strategy:**
The `Reply-To` header on outbound RFQs should be set to a monitored sales inbox (e.g. `rfq@company.com`), not the individual sender. This ensures all supplier replies land in one place that the whole team can monitor, regardless of who sent the RFQ.

---

### 10.3 Inbound Response Reality Map

Suppliers respond in at least seven distinct ways. The app must handle all of them gracefully:

| Response Type | How Common | What the Sales Team Does |
|---|---|---|
| **Reply email with price inline** | ~40% | Reads email, opens "Enter Quote" form, types in the numbers |
| **Reply email with PDF attachment** | ~25% | Opens PDF, reads numbers, opens "Enter Quote" form, types in the numbers |
| **Phone call** | ~20% | Takes notes during call, opens "Enter Quote" form afterward |
| **Reply with their own RFQ form** | ~8% | Opens their form, reads numbers, opens "Enter Quote" form |
| **No response** | ~5% | Marks RFQ as No Response after deadline passes |
| **Decline (won't quote)** | ~1% | Marks as Declined |
| **Reply asking for clarification** | ~1% | Replies, waits, then enters quote when they respond |

**Implication:** The "Enter Quote" form is used in 94% of all supplier interactions. It must be the fastest, most forgiving form in the application.

---

### 10.4 The Quote Entry Form — Design Requirements

This is the most-used screen in the app. Every design decision should optimize for **speed of entry** and **forgiveness** (easy to fix mistakes).

**Required fields — absolute minimum to save:**
1. Unit Price
2. Lead Time (days)

Everything else is optional on first entry and can be filled in later. The form should not block saving because a part number is missing.

**Pre-filled from context (never make the user type these):**
- Supplier name and CAGE (from the RFQ record)
- NSN (from the solicitation line)
- Nomenclature (from the solicitation line)
- Solicitation number (from context)
- Suggested bid price (auto-calculated: unit price × default markup %)

**Keyboard-first design:**
- Tab order: Unit Price → Lead Time → Part Number → Notes → Save
- Enter key on unit price field moves to lead time
- `Ctrl+Enter` or `Cmd+Enter` saves the form from anywhere
- No modal — quote entry should be an inline panel or dedicated page, not a popup that can be accidentally closed

**Smart defaults:**
- Lead time default: pre-fill with the RFQ's required delivery days as a starting point
- Part number: pre-fill from approved sources if only one source exists for this NSN
- Qty available: leave blank by default (optional)

**After save:**
- Solicitation status automatically advances to `QUOTING`
- Suggested bid price is calculated and shown immediately
- User is returned to wherever they came from (RFQ Center or Solicitation detail)
- A "Record Another Quote" button appears for the rare case of multiple quotes on one line

---

### 10.5 RFQ Tracking — What the Sales Team Needs to See

The RFQ Center Sent view must give the team a complete picture of outstanding supplier responses at a glance. Key information per RFQ:

- **Supplier name + email sent to** — so they know who to follow up with
- **Solicitation # and nomenclature** — so they know what they're waiting on
- **Sent date** — how long ago did we send this?
- **Return-by date** — is the deadline approaching?
- **Days remaining until deadline** — highlight red if ≤ 2 days
- **Response status** — Awaiting / Responded / Declined / No Response
- **Quick action buttons** — Enter Quote / Mark No Response / Resend / Follow Up

**Follow-up email:** A one-click "Follow Up" button should generate and send a brief follow-up email to the supplier ("Friendly reminder: we need your quote by [date] on [NSN]."). This should be a separate, shorter email template.

**Overdue RFQs:** When the return-by date passes with no response, the system should visually flag the RFQ. The sales team can then mark it "No Response" which removes it from the active queue and prevents it from blocking the solicitation from going "No Bid."

---

### 10.6 Database Additions for Email Tracking

**`dibbs_supplier_rfq`** — additions to existing model:
```python
# Additional fields for email tracking
email_message_id    = models.CharField(max_length=255, null=True, blank=True)
# Store the SMTP Message-ID so we can thread replies if email integration deepens
follow_up_sent_at   = models.DateTimeField(null=True, blank=True)
follow_up_count     = models.IntegerField(default=0)
notes               = models.TextField(null=True, blank=True)
# Internal notes about this RFQ (e.g. "called 3/8, said they'd reply by EOD")
declined_reason     = models.CharField(max_length=255, null=True, blank=True)
```

**`dibbs_supplier_contact_log`** — new table to track all supplier touchpoints:
```python
class SupplierContactLog(models.Model):
    CONTACT_METHOD = [
        ('EMAIL_OUT', 'Outbound Email'),
        ('EMAIL_IN',  'Inbound Email'),
        ('PHONE',     'Phone Call'),
        ('FOLLOWUP',  'Follow-up Email'),
        ('NOTE',      'Internal Note'),
    ]
    rfq         = models.ForeignKey('SupplierRFQ', on_delete=models.CASCADE,
                                     related_name='contact_log', null=True, blank=True)
    supplier    = models.ForeignKey('contracts.Supplier', on_delete=models.CASCADE,
                                     related_name='contact_log')
    solicitation = models.ForeignKey('Solicitation', on_delete=models.CASCADE,
                                      related_name='contact_log', null=True, blank=True)
    method      = models.CharField(max_length=20, choices=CONTACT_METHOD)
    direction   = models.CharField(max_length=3, choices=[('IN','Inbound'),('OUT','Outbound')])
    summary     = models.TextField()
    # For emails: the email body snippet. For calls: notes taken.
    logged_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    logged_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dibbs_supplier_contact_log'
        ordering = ['-logged_at']
```

**RFQ Inbox persistence (Microsoft Graph):** Supplier replies in the shared mailbox are listed live from Graph (50 messages per page load). When a rep links a message to one or more `SupplierRFQ` rows, the app stores `dibbs_inbox_message` (`InboxMessage`: Graph id, sender, subject, received time, HTML body) and `dibbs_inbox_message_rfq_link` (`InboxMessageRFQLink`: bridge to `dibbs_supplier_rfq`, optional note and `linked_by`). Unlinked messages are never written to the database. Email HTML is shown only inside a sandboxed iframe (`sandbox="allow-same-origin"`, no scripts). One email can link to multiple RFQs for grouped supplier replies. **Start Quote Entry** uses the existing `rfq_enter_quote` flow per linked RFQ.

---

### 10.7 Email Template Spec

**RFQ Email Template (full):**
```
Subject: RFQ: {solicitation_number} – {nomenclature} – Respond by {return_by_date}

{supplier_company_name},

We are requesting a quotation for the following government procurement item:

  Solicitation #:  {solicitation_number}
  Line #:          {line_number}
  NSN:             {nsn}
  Nomenclature:    {nomenclature}
  Quantity:        {quantity} {unit_of_issue}
  Req. Delivery:   {delivery_days} days ARO
  Quote Due By:    {return_by_date}
  {set_aside_line}

{approved_source_block}

To quote, please reply with:
  - Your unit price (5 decimal places if needed)
  - Lead time in days ARO
  - Your CAGE code
  - Part number being offered (if applicable)
  - Any exceptions or remarks

Reply directly to this email. All replies go to {reply_to_email}.

Quoter: {our_company_name} | CAGE: {our_cage} | {sender_name}
```

**Follow-up Email Template (brief):**
```
Subject: FOLLOW-UP: RFQ {solicitation_number} – {nomenclature} – Due {return_by_date}

{supplier_company_name},

This is a friendly reminder regarding our RFQ sent on {sent_date}.

  Solicitation:  {solicitation_number}  |  NSN: {nsn}
  Quote due:     {return_by_date}

If you are unable to quote, please reply with "No Bid" so we can proceed.

Thank you,
{sender_name}
```

**Variable definitions:**
- `{set_aside_line}` — only included if set-aside applies: `"Set-Aside: Small Business"`
- `{approved_source_block}` — only included if approved sources exist:
  ```
  Approved Source(s):
    CAGE {cage_1} / P/N {part_1}
    CAGE {cage_2} / P/N {part_2}
  ```

---

### 10.8 RFQ Center UI Specification (updated)

The RFQ Center is redesigned around the sales team's actual daily rhythm. A salesperson arrives in the morning, checks their email, and works through the queue. The app should mirror that mental model.

**Three-panel layout for the Sent RFQs view:**

```
┌──────────────────┬───────────────────────────────┬──────────────────────┐
│  LEFT PANEL      │  CENTER PANEL                 │  RIGHT PANEL         │
│  RFQ Queue       │  Selected RFQ Detail          │  Quote Entry         │
│  (scrollable     │  - Supplier info              │  (slides in when     │
│   list of all    │  - Solicitation detail        │   "Enter Quote"      │
│   sent RFQs,     │  - Contact log / notes        │   is clicked)        │
│   grouped by     │  - Email actions              │                      │
│   urgency)       │                               │                      │
└──────────────────┴───────────────────────────────┴──────────────────────┘
```

**Left panel — RFQ queue groups:**
1. 🔴 **Overdue** — return date passed, no response
2. 🟠 **Urgent** — return date ≤ 2 days, awaiting
3. 🟡 **Awaiting** — sent, no response yet
4. 🟢 **Responded** — quote received, pending bid
5. ⚫ **Closed** — declined, no response marked, or bid submitted

**Center panel — selected RFQ shows:**
- Supplier name, CAGE, email sent to
- NSN, nomenclature, quantity, return-by date
- Full contact log (all emails, calls, notes on this RFQ in chronological order)
- Action buttons: Enter Quote / Send Follow-Up / Mark No Response / Add Note / Decline

**Right panel — quote entry:**
- Slides in from the right when "Enter Quote" is clicked
- Only shows required fields prominently: Unit Price + Lead Time
- All other fields collapsed under "Additional Details ▼"
- `Ctrl+Enter` saves
- Does not navigate away — user stays in the RFQ Center after saving

**Inbox tab — supplier replies (Graph):** The RFQ Center **Inbox** tab links to `/sales/rfq/inbox/`, a two-panel page: recent messages from the `GRAPH_MAIL_SENDER` mailbox (read via Graph on each request; no background sync), message body loaded on demand, and **Link to RFQ** to attach a message to one or more sent RFQs. IMAP and per-CAGE mailbox settings are not used; configuration is environment-only (`GRAPH_MAIL_*`).

---

### 10.9 Solicitation-Level Communication View

Every solicitation detail page (the Matches, RFQs, and Quotes tabs) should also show a unified **Activity Feed** — a reverse-chronological log of all communication on that solicitation:

```
Mar 08 · 09:14  📤  RFQ sent to Military Surplus Corp (bids@militarysurplus.com)
Mar 08 · 09:14  📤  RFQ sent to Tactical Gear Inc (quotes@tacticalgear.com)
Mar 08 · 14:22  📥  Quote received — Military Surplus Corp: $38.15 / 12 days (entered by J. Davis)
Mar 08 · 16:01  📞  Phone note — Tactical Gear said they'll reply by EOD tomorrow (J. Davis)
Mar 09 · 08:55  📤  Follow-up sent to Tactical Gear Inc
Mar 09 · 11:30  📥  Quote received — Tactical Gear Inc: $36.00 / 10 days (entered by S. Chen)
```

This feed replaces the need to check multiple tabs. A salesperson can open a solicitation and immediately understand the full history of communication without clicking around.

---


---

## 11. Email Workflow — Lookup & PDF Handling

### 11.1 The Email Lookup Problem

The sales team's working environment is split between two windows: their email inbox and the app. When a supplier reply arrives, they need to get from that email to the right RFQ record in the app as fast as possible. The email may contain any of the following identifiers:

- Solicitation number (e.g. `SPE1C126T0694`) — most common, usually in the subject line because we put it there
- NSN (e.g. `8465-01-722-5469` or `8465017225469`) — often in the email body
- Supplier name or partial name (e.g. "Tactical Gear", "TGI")
- Supplier CAGE code (e.g. `8J931`) — sometimes in their signature
- Part number they are quoting (e.g. `TGI-DUFFL-MK2`) — often in the body
- Nomenclature (e.g. "duffel bag", "DUFFEL") — sometimes in a casual reply

The global search must handle all of these. It is the single most important navigation tool in the app for the sales workflow.

---

### 11.2 Global Search — Specification

**Search placement:** Persistent in the topbar on every page, not just the RFQ Center. The salesperson should not have to navigate anywhere to search — they should be able to type from whatever page they are on.

**Keyboard shortcut:** `/` (forward slash) focuses the search bar from anywhere in the app, matching the convention used by GitHub, Notion, and Linear. This means a salesperson can hit `/`, paste a solicitation number from their email, and hit Enter — three keystrokes from any page.

**What it searches (all fields simultaneously):**
| Field | Source | Example match |
|---|---|---|
| Solicitation number | `dibbs_solicitation` | `SPE1C126T0694` |
| NSN (formatted or raw) | `dibbs_solicitation_line` | `8465-01-722-5469` or `8465017225469` |
| Nomenclature | `dibbs_solicitation_line` | `duffel`, `BAG DUFFEL` |
| Supplier name | `contracts_supplier` (via matched RFQs) | `tactical gear`, `TGI` |
| Supplier CAGE | `contracts_supplier` | `8J931` |
| Part number quoted | `dibbs_supplier_quote` | `TGI-DUFFL-MK2` |
| Part number (approved source) | `dibbs_approved_source` | `L8A`, `4J12024-102B` |

**Search behavior:**
- Results appear as a dropdown after 2+ characters (no need to press Enter for quick lookup)
- Results are grouped: Solicitations first, then Suppliers
- Each result shows enough context to confirm it's the right one: sol number + nomenclature + status badge + days remaining
- Clicking a result navigates to the solicitation or RFQ detail
- Pressing Enter on the first result navigates immediately
- `Escape` clears and closes the dropdown
- NSN search normalizes the input: strips hyphens before matching, so `8465017225469` and `8465-01-722-5469` both hit the same record

**Django implementation:**
```python
# views.py — global search endpoint
def global_search(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    # Normalize: strip hyphens for NSN matching
    q_raw = q.replace('-', '').replace(' ', '')

    solicitations = Solicitation.objects.filter(
        Q(solicitation_number__icontains=q) |
        Q(lines__nsn__icontains=q) |
        Q(lines__nsn__icontains=q_raw) |
        Q(lines__nomenclature__icontains=q) |
        Q(rfqs__supplier__name__icontains=q) |
        Q(rfqs__supplier__cage_code__icontains=q) |
        Q(rfqs__quotes__part_number_offered__icontains=q) |
        Q(approved_sources__approved_cage__icontains=q)
    ).distinct().select_related().prefetch_related(
        'lines', 'rfqs__supplier'
    )[:12]

    results = [{
        'type': 'solicitation',
        'sol_number': s.solicitation_number,
        'nomenclature': s.lines.first().nomenclature if s.lines.exists() else '',
        'nsn': s.lines.first().nsn if s.lines.exists() else '',
        'status': s.status,
        'days_remaining': s.days_remaining,
        'url': f'/sales/solicitations/{s.solicitation_number}/',
    } for s in solicitations]

    return JsonResponse({'results': results})
```

---

### 11.3 RFQ Center Search — In-Queue Lookup

In addition to the global topbar search, the RFQ Center left panel has its own queue filter. This is for when the salesperson is already in the RFQ Center and wants to narrow down the list. It filters live across all visible queue rows.

**The queue search matches:**
- Supplier name
- Solicitation number
- NSN
- Nomenclature

All four fields visible in each queue row are searched simultaneously on every keystroke.

---

### 11.4 PDF Files — Decision

**What DIBBS provides:**
The `IN` file column 80–98 contains the PDF filename for each solicitation (e.g. `SPE1C126T0694.pdf`). These are the official government solicitation documents hosted on DIBBS servers at a predictable URL:
```
https://www.dibbs.bsm.dla.mil/Docs/RFQ/{pdf_filename}
```

**Decision: Link only. No download, no storage, no attachment.**

The app stores the `pdf_file_name` from the IN file (already in `dibbs_solicitation.pdf_file_name`) and constructs the URL at runtime. Suppliers receive the direct DIBBS link in the RFQ email body. There is nothing to store, nothing to sync, and the supplier always gets the authoritative document straight from the government source.

**Model property** (implemented in `sales/models/solicitations.py`):
```python
@property
def dibbs_pdf_url(self):
    if self.pdf_file_name and self.solicitation_number:
        subdir = self.solicitation_number[-1].upper()
        return f"https://dibbs2.bsm.dla.mil/Downloads/RFQ/{subdir}/{self.pdf_file_name.upper()}"
    return None
```

> ⚠ **Parser note:** `parse_procurement_history()` uses `pypdf` to extract text directly from the raw PDF blob. DIBBS does not serve ZIPs for individual solicitation PDFs — the blob stored in `pdf_blob` is always a raw PDF. The procurement history section appears inline in the PDF text (Section A / Section B pages) and is parsed via regex after text extraction.

> **Background fetch pipeline:** `pdf_fetch_status` and `pdf_fetch_attempts` drive queue-driven fetches. **`auto_import_dibbs`** (nightly) performs **set-aside PDF harvest** in **batches of 10** — one Playwright session per batch, full browser restart between batches — storing **`pdf_blob`**, then a separate **Loop C** (`parse_pdf_data_backlog`) runs **only after** all harvest sessions close. Fifth failed fetch sets `pdf_data_pulled` (no blob) to cap retries. **`fetch_pending_pdfs`** is optional/manual (deprecated as the default 5‑minute job); it uses the same batch-of-10 pattern for `PENDING`/`FAILED` queue sols, then the shared parse backlog.

> **`auto_import_dibbs` WebJob** — **Loop A:** RFQDates scrape (IN + BQ links only) → reconcile `ImportBatch` → `fetch_dibbs_archive_files()` (IN txt + BQ zip; **AS extracted from BQ zip**; no CA zip) + `run_import()`. **Loop B:** global set-aside sols with no `pdf_blob`, `pdf_fetch_attempts < 5`, `pdf_data_pulled` null — fetch **10 PDFs per Playwright session**, close browser, repeat. **Loop C:** `parse_pdf_data_backlog()` — parse every stored blob with null `pdf_data_pulled`; `persist_pdf_procurement_extract` **always** sets `pdf_data_pulled` even when parsers find nothing. Alerts on IN/BQ/AS import failures only.

> ⚠ **Note:** The original spec URL (`https://www.dibbs.bsm.dla.mil/Docs/RFQ/{filename}`) was incorrect. The live URL format uses `dibbs2.bsm.dla.mil/Downloads/RFQ/{last_char_of_sol_number}/{filename}` — subdirectory is derived from the last character of the solicitation number. Already corrected in production.

**Automated procurement extract (nightly import):** No `ca{yymmdd}.zip` download in `dibbs_fetch`. AS text ships inside **`bq{yymmdd}.zip`**. Set-aside PDFs are stored in **`pdf_blob`** and parsed in a dedicated post-browser phase. **`parse_ca_zip()`** in `ca_parser.py` remains an optional legacy/ad-hoc bulk path, not used by the nightly WebJob. **`fetch_ca_zip`** was removed from `dibbs_fetch.py`.

**In-app PDF viewer (Review Workbench):** The primary source for opening an RFQ PDF in the browser is the stored `Solicitation.pdf_blob` served by `solicitation_pdf_view` (`/sales/solicitations/<sol_number>/pdf/`, `Content-Disposition: inline`). If `pdf_blob` is empty, that view sets `pdf_fetch_status` to `FETCHING`, runs Playwright `fetch_pdf_for_sol`, persists the bytes, runs procurement-history and Section D packaging extraction, updates `pdf_fetched_at` / `pdf_data_pulled`, then returns the PDF. Outbound RFQ email bodies continue to use the direct DIBBS URL (`dibbs_pdf_url`) so suppliers still receive the government-hosted link.

**In the RFQ email template**, include the link in the body:
```
Solicitation PDF: https://dibbs2.bsm.dla.mil/Downloads/RFQ/{subdir}/{pdf_filename}
```

**In the app UI**, the Review Workbench **View RFQ PDF** control uses the `pdf_blob` route above (with on-demand fetch when missing). Other surfaces may still link to `dibbs_pdf_url` where a direct DIBBS tab is appropriate.

---

### 11.5 Summary of Decisions

| Question | Decision | Rationale |
|---|---|---|
| Where do PDFs live? | On DIBBS servers for supplier-facing links; in-app viewing uses `pdf_blob` when fetched | Email uses authoritative DIBBS URL; workbench can cache bytes for parsing and inline display |
| How do suppliers get the PDF? | Direct DIBBS link included in RFQ email body | Simple, reliable; supplier gets it from the official government source |
| How do salespeople view PDFs? | Review Workbench serves `pdf_blob` inline (`solicitation_pdf_view`), fetching via Playwright if missing | Enables procurement history + packaging extraction and avoids relying on the browser alone for slow DIBBS downloads |
| How do salespeople look up a supplier reply? | Global topbar search, `/` shortcut, matches sol#/NSN/name/CAGE/part# | Works from any page without navigation; handles any identifier in the email |
| Search field normalization | Strip hyphens from NSN input before matching | `8465017225469` and `8465-01-722-5469` both hit the same record |

---

## 13. Session 7 — Remaining Work & Go-Live Checklist

*What remains before the app is fully operational for daily use.*

### 13.1 Go-Live Blockers (Must Complete Before Cutover)

| # | Item | Action | Notes |
|---|------|--------|-------|
| 1 | Email not configured | Set `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` in `settings.py` | RFQ emails will silently fail until this is done |
| 2 | No CompanyCAGE record | Create via Django admin — set `is_default=True`, populate all fields including `smtp_reply_to` | Bid builder and BQ export will error without it |
| 3 | ~~`supplier_list` `archived` field~~ | ✅ Resolved — `archived = BooleanField(default=False)` confirmed on `contracts_supplier`. No change needed. | |
| 4 | `hubzone_requested_by` missing from `Solicitation` model | Add `hubzone_requested_by = CharField(max_length=100, blank=True, default='')` to `sales/models/solicitations.py` + run migration | Required before HUBZone bulk-flag UI in S7 can be built |

### 13.2 Session 7 — Recommended Build Tasks

These are the highest-value remaining items that can be completed in one Cursor session:

| Priority | Task | Detail |
|----------|------|--------|
| 🔴 High | HUBZone bulk-flag UI | Add checkboxes to solicitation list + "Mark as HUBZone" POST action. Travis sends a daily screenshot — staff needs to quickly mark 5–15 solicitations. One button, one POST, done. |
| 🔴 High | Settings page — CompanyCAGE management | `/sales/settings/cages/` — list, add, edit CompanyCAGE records. Required so non-dev staff can set up the CAGE without Django admin access. |
| 🟡 Med | `no_bid` action on solicitation detail | Verify the existing `no_bid` view is wired to the solicitation detail Bid tab's "No Bid" button |
| 🟡 Med | Import History page | `/sales/import/history/` — simple table of ImportBatch records with date, file names, row counts |
| 🟡 Med | Bid History page | `/sales/bids/history/` — submitted bids with outcome tracking (WON/LOST/NO_BID assignment) |
| 🟢 Nice | Dashboard urgent badge on nav | Show count of RFQs overdue in the RFQ Center nav item |

### 13.3 What a Complete Daily Workflow Looks Like

After Session 7, the full daily cycle should be:

```
1. David downloads IN + BQ + AS files from DIBBS
2. Upload at /sales/import/ → matching runs automatically
3. Review new solicitations → triage buckets (SDVOSB auto, HUBZone manual, Growth/Skip auto)
4. RFQ Center Pending → review matches → Send RFQs
5. RFQ Center → monitor responses → Enter Quotes as suppliers respond
6. Bid Center Ready to Bid → Build Bid for each quoted line
7. Export Queue → Export BQ file → Upload to DIBBS
```

---

## 12. Sales Team Feedback — Demo Review (Mar 2026)

*Captured from sales team demo session transcript.*

---

### 12.1 Overall Reaction

Positive. The pipeline layout, matching logic, and RFQ center all resonated immediately. The team understood the workflow without explanation. Primary concern is build timeline — the existing platform (Sales Patriot) has until end of month.

---

### 12.2 The Three-Bucket Triage Model ⚠ NEW REQUIREMENT

This is the most significant design addition from the demo session. The sales team does **not** work all 544 daily solicitations equally. They described a three-tier mental model that needs to be built into the app as a triage/filter step between import and RFQ dispatch:

| Bucket | Label | Criteria | How Assigned |
|--------|-------|----------|--------------|
| 🟢 | **Priority 1 — SDVOSB** | Set-aside code = SDVOSB | Auto on import — STATZ is a Service Disabled Veteran Owned Small Business, these are the core business |
| 🔵 | **Priority 2 — HUBZone** | Flagged by HUBZone partner | Manually flagged — partner sends a list, staff marks these in the app |
| 🟡 | **Growth** | Tier 1 or Tier 2 supplier match exists | Auto on import — matching engine found a known supplier via contract history or approved source |
| ⚫ | **Skip** | Unrestricted, IDC, no match found | Auto on import — default for anything that doesn't meet above criteria |

**Key quote:** *"We need to figure out which ones we know for sure we're not even going to look at, cross those off the list, and then there will be the ones on the other spectrum — these are the ones we know we're going to get on."*

**Why SDVOSB is Priority 1:** STATZ is an SDVOSB. These set-asides are reserved for companies like STATZ — they are the highest-probability wins and should always be worked first.

**Why HUBZone is manually flagged not auto-detected:** HUBZone bids come through a partner company, not directly from STATZ's set-aside status. The partner sends over a list of solicitations they want worked. These can't be auto-detected from the IN file set-aside code alone — they need to be marked by staff when the partner's list arrives. The `bucket` field supports a `HUBZONE` value and a `hubzone_requested_by` note field for this purpose.

**Why unrestricted is Skip:** Any unrestricted solicitation can be bid by the supplier directly. Suppliers routinely quote for the company then undercut and bid direct. In 4 months the team has seen ~5 unrestricted wins. Not worth pursuing as a rule, though staff can manually promote any Skip to Growth if there's a compelling reason.

**Why IDCs are Skip:** Low value, high back-and-forth, government uses them to drive prices down. Default skip, can be manually promoted.

**Implementation — Solicitation Filter Rules (`dibbs_filter_rule` table):**

```python
class SolicitationFilterRule(models.Model):
    BUCKET = [
        ('SDVOSB',   'Priority 1 — SDVOSB'),
        ('HUBZONE',  'Priority 2 — HUBZone'),
        ('GROWTH',   'Growth — Supplier Match'),
        ('SKIP',     'Skip — Do Not Work'),
    ]
    rule_name         = models.CharField(max_length=100)
    bucket            = models.CharField(max_length=10, choices=BUCKET)
    # Match criteria — any combination triggers the rule
    set_aside_code    = models.CharField(max_length=10, blank=True)
    # 'SDVOSB' auto-assigns Priority 1; blank = unrestricted → Skip
    solicitation_type = models.CharField(max_length=10, blank=True)
    # e.g. 'IDC' to skip all IDC solicitations
    fsc_code          = models.CharField(max_length=4, blank=True)
    # skip entire FSC categories the company never bids
    notes             = models.TextField(blank=True)
    is_active         = models.BooleanField(default=True)
    created_by        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'dibbs_filter_rule'
```

**Add `bucket` field to `dibbs_solicitation`:**
```python
BUCKET_CHOICES = [
    ('UNSET',    'Not Yet Triaged'),
    ('SDVOSB',   'Priority 1 — SDVOSB'),
    ('HUBZONE',  'Priority 2 — HUBZone'),
    ('GROWTH',   'Growth'),
    ('SKIP',     'Skip'),
]
bucket              = models.CharField(max_length=10, choices=BUCKET_CHOICES, default='UNSET')
bucket_assigned_by  = models.CharField(max_length=20, default='auto')
# 'auto' = filter rules on import; 'manual' = staff override; 'hubzone' = HUBZone partner flag
hubzone_requested_by = models.CharField(max_length=100, blank=True)
# Name/note of who from the HUBZone partner requested this solicitation be worked
```

**Seeded filter rules (applied on every import automatically):**

| Rule | Set-Aside Code | → Bucket |
|------|---------------|---------|
| SDVOSB Set-Aside | `SDVOSB` | Priority 1 — SDVOSB |
| Unrestricted | *(blank)* | Skip |
| IDC | solicitation_type = `IDC` | Skip |
| *All others* | — | UNSET → Growth if match found, else Skip |

**Triage logic runs at import time:**
After parsing the IN file, the import service runs each new solicitation through the active filter rules and assigns a bucket automatically. Users can manually override any assignment.

**Pipeline and solicitation list filter by bucket:**
- Dashboard shows counts by bucket
- Default solicitation list view shows PRIORITY first, then GROWTH, SKIP collapsed/hidden
- A "Skip Queue" view exists for audit purposes — nothing disappears, it just moves out of the active working set

---

### 12.3 Supplier Capability Data — Contracts Database ✅ RESOLVED

**The NSN-to-supplier history already exists in the company's own database.** STATZ has 20+ years and 10,000+ completed or in-progress contracts. The data model is:

```
contracts_contract
  └── contracts_clin (one-to-many)
        ├── supplier_fk  →  contracts_supplier
        └── nsn_fk       →  (NSN record)
```

**Architecture decision:** `contracts` and `sales` remain separate Django apps. **Tier-1 NSN scores** are computed in SQL Server view **`dibbs_supplier_nsn_scored`** (see `sales/sql/dibbs_supplier_nsn_scored.sql`), which joins `dibbs_supplier_nsn` to `contracts_clin`, `contracts_contract`, and `contracts_nsn`. Django matching reads the view through unmanaged **`SupplierNSNScored`** — Python does not query `Clin` for matching.

```
Staff / quotes ──→ dibbs_supplier_nsn
                         │
contracts_clin + contracts_contract + contracts_nsn ──→ dibbs_supplier_nsn_scored (VIEW)
                         │
                         ▼
              matching (SupplierNSNScored) ──→ dibbs_supplier_match
```

**Packaging facilities:** If packaging-only suppliers must never appear in tier 1, filter them when **creating** `dibbs_supplier_nsn` rows or extend the view SQL to exclude `contracts_supplier.is_packhouse = 1`. The view DDL shipped in-repo is the source of truth for the exact join filters.

---

### 12.3.1 Contract history weighting (live view)

Recency weighting is applied **inside** `dibbs_supplier_nsn_scored` (not in Python). Each matching `contracts_clin` row with a non-null contract `award_date` adds:

| Age (calendar days from award to today) | Weight per contract |
|---|---|
| ≤ 730 (~2 years) | 1.0 |
| ≤ 1460 (~4 years) | 0.75 |
| Older | 0.5 |

**Base bonus:** Every row in `dibbs_supplier_nsn` contributes **+1.0** to `match_score` in the view so manually added capabilities rank above zero but below suppliers with strong contract history.

**What the score drives:** Order of Tier 1 matches on solicitation Matches tab and import-time `dibbs_supplier_match.match_score` for tier 1.

**Confirmed:** `award_date` lives on `contracts_contract`. NSN text for the join uses `contracts_nsn.nsn_code` matched to `dibbs_supplier_nsn.nsn` (normalized 13-digit, no hyphens).

---

### 12.4 Multiple CAGE Support

Currently the company bids under a single CAGE. EDP submits to DIBBS on their behalf and takes a percentage. The `dibbs_company_cage` table already supports multiple CAGEs — no design change needed, but the Settings page should make it easy to add a second CAGE if the relationship with EDP changes or additional CAGEs are acquired.

---

### 12.5 RFQ Auto-Build Confirmation

The team confirmed the RFQ email only needs 5–6 fields, all of which are present in the IN file:

- Solicitation number
- NSN
- Nomenclature
- Quantity + Unit of Issue
- Required delivery days
- Return-by date
- Set-aside type (if applicable)

All of these are already parsed into `dibbs_solicitation` and `dibbs_solicitation_line` at import time. The RFQ email can be fully auto-generated with no manual data entry. This is already specced in §10.2 and §10.7.

---

### 12.6 Dark Mode

Requested explicitly by the sales team. Add to Phase 3 polish items.

---

### 12.7 Timeline

**Hard deadline: End of March 2026.** Sales Patriot platform access ends. The app needs to be functional enough to handle daily imports and RFQ dispatch by that date. Phase 1 completion is the minimum viable cutover target.

---

## 13. Awards File Import

### 13.1 Overview
DIBBS publishes daily award data on its portal. STATZ scrapes this data automatically each night via a Django management command (`scrape_awards`) triggered by an Azure WebJob. Award records are written directly to `DibbsAward` with no intermediate file. The manual AW file upload at `/sales/awards/import/` is retained as a fallback if the automated scraper fails. `AwardImportBatch` tracks both paths, distinguished by the `source` field (`FILE_UPLOAD` vs `AUTO_SCRAPE`). This is a separate workflow from the daily IN/BQ/AS import; SAM.gov awards sync was removed (DIBBS is the sole source for `DibbsAward` file-style rows).

**SAM.gov entity (CAGE) cache:** `SAMEntityCache` (`dibbs_sam_entity_cache`) stores structured SAM Entity Management v3 lookup results per CAGE for **30 days** (TTL). Rows are created/updated **on demand** when a user loads the standalone entity lookup page (`/sales/entity/cage/<cage>/`, `get_or_fetch_cage`); there is no import/WebJob pre-warm. Failed lookups can be cached with `fetch_error=True` to avoid repeated API calls. Table is not exposed in Django admin.

### 13.2 AW File Format
Filename format: `aw[YYMMDD].txt` (e.g. `aw260319.txt`). File is CSV with `#`-prefixed comment
header lines, followed by a `Row_Num,...` column header row, then data rows. Columns:
Row_Num, Award_Basic_Number, Delivery_Order_Number, Delivery_Order_Counter, Last_Mod_Posting_Date,
Awardee_CAGE_Code, Total_Contract_Price (format: `$1 234.56`), Award_Date, Posted_Date,
NSN_Part_Number, Nomenclature, Purchase_Request, Solicitation. All dates: MM-DD-YYYY.

### 13.3 Data Model
`DibbsAward` is populated from AW originals (`last_mod_posting_date IS NULL`) and includes
`is_faux` to mark synthesized placeholders. `DibbsAwardMod` stores AW modification rows
(`last_mod_posting_date IS NOT NULL`) in table `dibbs_award_mod` linked to `DibbsAward`.
`AwardImportBatch` tracks each upload or scrape with counters for:
`awards_created`, `faux_created`, `faux_upgraded`, `mods_created`, `mods_skipped`, plus for automated scrapes: `source`, `scrape_date`, `expected_rows`, `scrape_status`, `last_attempted_at`.

Original-award dedup key in `DibbsAward` import path:
`(award_basic_number, delivery_order_number, nsn)`.

MOD dedup key in `DibbsAwardMod`:
`(award_id, mod_date, nsn, mod_contract_price)`.

### 13.4 Solicitation Matching
During import, `dibbs_solicitation_number` from the AW file is looked up against
`Solicitation.solicitation_number`. If a match is found, the FK is set. Many AW rows reference
solicitations not in the system (different date, already archived, etc.) — these are stored with
`solicitation=None` and `dibbs_solicitation_number` preserved as a raw string.

Routing logic:
- If `last_mod_posting_date IS NULL`, process row as original award (`DibbsAward` path).
- If `last_mod_posting_date IS NOT NULL`, process row as MOD (`DibbsAwardMod` path).

Faux synthesis (MOD-first scenario):
- If MOD row has no matching award key, create a faux `DibbsAward` first (`is_faux=True`).
- Faux `award_date` is fiscal year end (Sep 30) derived from `award_basic_number[6:8]`
  (`"24"` -> `2024-09-30`), with fallback to parsed AW file date if extraction fails.
- Then insert `DibbsAwardMod` linked to that faux award.

### 13.5 We Won Detection
`we_won` is set to `True` when `awardee_cage` matches any active `CompanyCAGE.cage_code`
(case-insensitive). If no active company CAGEs exist, `we_won` stays `False` for imported rows.

### 13.6 Solicitation Detail — Last Award Block
The solicitation detail Overview tab shows a "Last Award" card when a `DibbsAward` record exists
for the line's NSN (ordered by `award_date` descending). This gives the sales team instant context
on who last won and at what price — critical for bid pricing decisions.

### 13.7 Automated Scraper

**Entry point:** `python manage.py scrape_awards` (full reconciliation) · `python manage.py scrape_awards --date YYYY-MM-DD` (single date, skips reconciliation) · `python manage.py scrape_awards --dry-run` (inventory + queue only)  
**Service:** `sales/services/dibbs_awards_scraper.py`  
**Scheduler:** Azure WebJob — `webjobs/run_scrape_awards/run.sh`  
**Schedule:** Nightly (configure time in Azure portal)

**Architecture — four phases.** Django ORM must never run inside `with sync_playwright()` when using the mssql backend on Azure App Service (Playwright’s event loop conflicts with the driver’s DB connection). All database access is outside browser sessions, except passing plain Python data into/out of Playwright.

**Phase 1 — Inventory (browser, no ORM)**  
Launch headless Chromium, accept the DoD warning, navigate to `AwdDates.aspx?category=post`, parse all available award dates from link `href`s (`Value=MM-DD-YYYY`), close the browser. Returns the date list sorted oldest-first.

**Phase 2 — Sync dates to DB (pure ORM)**  
For each date returned by Phase 1 that does not yet have an `AwardImportBatch` with `source=AUTO_SCRAPE`, insert a row with `scrape_status=MISSING` (never downgrade existing rows).

**Phase 3 — Scrape loop (one browser session per date)**  
Build a queue of all `AUTO_SCRAPE` batches where `scrape_status` is not `SUCCESS`, ordered by `scrape_date` ascending. Skip `IN_PROGRESS` rows whose `last_attempted_at` is within the last 30 minutes (parallel-run guard). For each queued batch: mark `IN_PROGRESS` (ORM), then call `scrape_awards_for_date()`, which opens Playwright, paginates `AwdRecs.aspx` for that date, and after **each page** invokes `on_page_complete(records, page_num, total_pages)` — that callback runs outside the browser’s async context and calls `import_aw_records()` so rows are persisted incrementally (not held in memory for the whole date). After the browser closes, set final `scrape_status` (SUCCESS / PARTIAL / FAILED), `expected_rows`, `pages_scraped`, `last_attempted_at`.

**Phase 4 — Notification check (pure ORM + optional Graph mail)**  
See §13.8.

**Per-date scrape target:** `https://www.dibbs.bsm.dla.mil/Awards/AwdRecs.aspx?Category=post&TypeSrch=cq&Value=MM-DD-YYYY`

**Success condition:** `actual_rows == expected_rows` AND no exception thrown.  
**PARTIAL:** Scraper finished pagination but row count mismatch; data from completed pages remains.  
**FAILED:** Exception during scrape; `AwardImportBatch` is marked FAILED. Manual upload fallback should be used.

**Idempotency:** Queue excludes `SUCCESS`. `DibbsAward` rows are upserted using the existing dedup key; per-page imports accumulate batch counters in `_process_records` when reusing the same `AwardImportBatch`.

### 13.8 Danger zone — retention alerts

DIBBS retains roughly **45 days** of award history. Any `AUTO_SCRAPE` `AwardImportBatch` with `scrape_status` other than `SUCCESS` and with `scrape_date` at least **38 days** before today is treated as at risk of falling off DIBBS before it is scraped.

**Behavior:** After each full reconciliation run (not `--date`), the management command evaluates this condition. If any rows match, it sends **one** consolidated email via Microsoft Graph (`send_mail_via_graph`) to the address in environment variable **`AWARDS_ALERT_EMAIL`** (also set `GRAPH_MAIL_ENABLED` and the same Graph credentials as RFQ mail). The awards import history page (`/sales/awards/import/`) shows an **alert banner** listing the same at-risk batches.

### 13.9 Wins Report (Dynamic Company CAGE Join)
Wins are determined dynamically from active company CAGE configuration, not from the static
`DibbsAward.we_won` field. A SQL Server view identifies winning award row IDs by joining
`dibbs_award.awardee_cage` to active `dibbs_company_cage.cage_code` values case-insensitively.

**Important:** This view is created manually in SSMS by a developer/DBA. It is not managed
by Django migrations.

```sql
CREATE VIEW [dbo].[dibbs_we_won_awards] AS
SELECT da.[id]
FROM [dbo].[dibbs_award] da
INNER JOIN [dbo].[dibbs_company_cage] cc
    ON UPPER(da.[awardee_cage]) = UPPER(cc.[cage_code])
WHERE cc.[is_active] = 1
```

The Django app exposes this view via unmanaged model `WeWonAward`:
- `managed = False`
- `db_table = 'dibbs_we_won_awards'`
- Typical usage: `DibbsAward.objects.filter(id__in=WeWonAward.objects.values('id'))`

UI surface:
- Dashboard card: **Wins This Month** on `/sales/` (links to wins report).
- Wins report page: `/sales/awards/wins/` (URL name `sales:awards_wins`), grouped by
  `(award_basic_number, delivery_order_number)` and paginated by group.

---

