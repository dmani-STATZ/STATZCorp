---
id: 2026-07-07-nsn-portal-launch
title: NSN Portal — research NSNs, suppliers, and pricing in one place
published: false
publish_date: 2026-07-07
tags: [new, sales]
critical: false
---

## What's new

The **NSN Observatory** is now live at **Products → NSN Portal** (`/products/`). From one search box you can look up:

- A full **NSN** or **NIIN** and jump straight to that item's dossier
- A supplier **CAGE** and see every NSN they are approved on, have quoted, or have won
- A **part number** or description keyword across approved sources, quotes, and the NSN catalog

## NSN Dossier

Each NSN has a dedicated page that pulls together government purchase history, approved sources (with part numbers), our quotes and bids, DIBBS awards, linked contracts, and solicitation demand — plus a price chart when data exists.

## Logistics editing

You can now update **unit weight**, **dimensions**, and **packaging notes** directly on the NSN dossier via **Edit logistics**. Sales workflows that read packout data from the catalog will pick up your changes immediately.

## Fix & polish (2026-07-07)

- **Standard site header** restored on all portal pages — the custom striped banner is removed; Observatory, Dossier, and Supplier NSN View inherit the same header as contracts pages.
- **Recent awards panel** now orders by AW file date (not award date), deduplicates on contract + delivery order, and shows hyphen-formatted NSNs.
- **Government purchase records** stat uses an unfiltered procurement-history count; numbers across the portal use thousands separators.
- **Visual polish** — stat cards, omnibox, panels, and empty states aligned with existing contracts card/table patterns and theme tokens.

## Fixes

- **Price chart on the NSN Dossier** now renders in a fixed-size panel instead of leaving a large blank area above the fold when award or quote data exists.
- **CAGE search in the Observatory** correctly finds suppliers again when you enter a 5-character CAGE code (including codes stored with extra spacing in the database).
- **Site header on portal pages** no longer hidden under a pinned panel title — the real header (logo, nav, company selector, theme toggle, user info) shows at the top of Observatory and Dossier pages, matching `/contracts/`.
- **Price Intelligence chart** loads from vendored static files (Chart.js 4.4.1) so it renders in restricted environments; the panel now sits at the bottom of the NSN Dossier, below Demand History.
