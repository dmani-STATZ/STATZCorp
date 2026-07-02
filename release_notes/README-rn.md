# Release notes (author workflow)

Product release notes live in this folder as **one markdown file per note**. Files are reconciled into the database by the Django management command `import_release_notes` (also run from `startup.sh` on deploy).

## File naming

- Path: `release_notes/<id>.md`
- **Filename (without `.md`) must equal the `id` field** in frontmatter.
- Convention: `YYYY-MM-DD-short-slug.md` (example: `2026-05-11-contracts-bulk-export.md`).

## Frontmatter (required)

```yaml
---
id: 2026-05-11-contracts-bulk-export   # must match filename stem
title: Human-readable title
published: true                      # false = file skipped on import
publish_date: 2026-05-11             # ISO date; ordering + new-user gating
tags: [new, contracts]               # exactly one change type + one area
critical: false                      # stored only; reserved for future UI
---
```

### Tag taxonomy

`tags` must be a **list of exactly two strings**:

1. One from **change types:** `new`, `improved`, `fixed`, `breaking`
2. One from **areas:** `contracts`, `finance`, `sales`, `training`, `system`

Order does not matter. Unknown tags cause the file to be **skipped** (warning logged).

## Body

Markdown only. The database stores the markdown source; HTML is rendered at display time.

## Validation (import)

Each rule is enforced per file. On failure the file is skipped, a warning is logged, and startup continues.

- `id` present and matches the filename stem
- `title` non-empty
- `publish_date` parseable as a date
- `tags`: exactly one change type and one area (two entries total)
- Body non-empty after trim
- `published` / `critical` must be booleans

## Author workflow

1. On a dev branch, add `release_notes/YYYY-MM-DD-slug.md` with **`published: false`** so imports on shared environments skip it.
2. When ready to ship, set **`published: true`**, commit, and deploy.
3. Deploy runs `python manage.py import_release_notes`, which inserts new rows or updates changed content. **Existing acknowledgements are never invalidated** when a note is edited.

## Commands

```bash
python manage.py import_release_notes             # normal import
python manage.py import_release_notes --dry-run   # no DB writes
python manage.py import_release_notes --verbose   # extra logging
```

## Database vs files

- The markdown files are the **source of truth** for published content.
- The DB is a **cache** for queries and UX (blocking modal, `/whats-new/` archive).
- Rows are **never** deleted automatically if a file disappears; warnings are logged for orphan DB rows (cleanup is manual).

## Recent release notes

- [2026-07-02-dfas-import-review](2026-07-02-dfas-import-review.md) — DFAS import review: per-row and bulk apply, re-match, match preview, explicit batch close.
- [2026-06-30-dashboard-non-numeric-item-number](2026-06-30-dashboard-non-numeric-item-number.md) — Fixed Contracts Dashboard crash when CLIN item numbers contain letters (e.g. `0001AA`).
- [2026-06-30-supplier-contact-categories](2026-06-30-supplier-contact-categories.md) — Contact Categories replace Contact Groups and `is_primary`.
- [2026-06-30-rfq-sales-contact-dispatch](2026-06-30-rfq-sales-contact-dispatch.md) — RFQ dispatch uses Sales-category contacts; legacy RFQ Email deprecated.
