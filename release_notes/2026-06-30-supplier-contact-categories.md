---
id: 2026-06-30-supplier-contact-categories
title: Supplier Contact Categories Replace Groups and Primary Flag
published: true
publish_date: 2026-06-30
tags: [improved, contracts]
critical: false
---

Supplier contacts now use a global **Contact Categories** taxonomy instead of per-supplier Contact Groups and the retired `is_primary` flag.

- **Admin-editable categories:** Primary, Contracts, Sales, Leadership, and Finance (seeded globally; manage under Django admin).
- **Primary is a category:** Multiple contacts per supplier may hold the Primary category. Legacy `is_primary` rows and "Primary Contacts" group members were migrated automatically.
- **Contact Groups removed:** The supplier detail Contact Groups section and its CRUD endpoints are gone.
- **Category assignment API:** `POST /suppliers/<pk>/contact/<contact_id>/categories/` with `category_ids` (comma-separated active category IDs).
- **Contact-card category picker (frontend):** Each contact card shows display-only red pills for assigned categories (Primary appears as a pill like any other — no separate badge). A **Categories** dropdown beside Edit/Delete opens a checklist of all active categories; inactive assigned categories appear muted for removal only. Changes save when the dropdown closes (if the selection changed), via the category API — pills and the Primary card border update in place without a page reload. Contact cards are laid out four-per-row (`col-3`) with info on the left and Edit/Delete/Categories stacked vertically on the right.
