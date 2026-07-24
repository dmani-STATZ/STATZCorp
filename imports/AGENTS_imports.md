# imports/AGENTS.md

## Purpose
Standalone generic data import manager. Allows importing CSV/Excel files,
mapping spreadsheet columns to Django model fields, fuzzy-matching rows
against existing records, previewing proposed changes, and committing
approved updates to the database.

## Key Design Principles
1. **Generic by design** — no hardcoded field logic for any specific model.
   Target models are registered in `imports/config.py` only.
2. **Introspective** — uses Django's `apps.get_model()` to discover fields
   at runtime. Never assume field names in the engine.
3. **Dry-run first** — ImportSession must reach 'previewing' status before
   any commit is allowed. No direct writes without user approval.
4. **Single commit seam** — all DB writes at commit time go through
   `commit_row()` in `imports/services.py`. This is the
   only place writes happen, making future transaction-system integration
   a one-function swap.
5. **ValueTranslationMap learns** — when a user manually resolves an FK
   during preview, auto-save to ValueTranslationMap so future imports
   benefit. Show a visible indicator when a translation is saved.

## Models
- `ImportSession` — one per uploaded file. Tracks status, column mapping,
  target model, and match field.
- `ImportRow` — one per spreadsheet row. Holds raw data, proposed changes,
  match confidence, and matched_target_id (plain IntegerField, not a real FK).
- `ValueTranslationMap` — reusable raw_value → resolved_id lookup.
  Scoped per target_model + target_field.

## Config
`imports/config.py` — IMPORT_TARGETS dict. Add new target models here only.
Current targets: suppliers.Supplier

## URL Namespace
`imports:`

## Status Flow
draft → previewing → committed

## Future: Transaction Integration
When the transaction/audit system is ready to be wired in, replace the
body of `commit_row()` in `imports/services.py`. No other files should
need changes.

## 16. Services Architecture

All import logic lives in `imports/services.py`. The functions and their 
single responsibilities:

| Function | Responsibility |
|---|---|
| parse_uploaded_file | File → (headers, rows). In-memory only. |
| normalize_for_matching | String cleanup for fuzzy comparison. |
| token_sort | Word-order normalization before SequenceMatcher. |
| fuzzy_match_row | Find best matching record in target model. |
| resolve_fk_value | Look up ValueTranslationMap for a raw value. |
| save_translation | Upsert ValueTranslationMap entry. |
| process_session | Full matching pass for a session. |
| commit_row | ONLY place target model is written. Single seam for V2. |
| commit_session | Commit all approved rows in a session. |

**The commit seam rule:** Never write to the target model outside of 
`commit_row()`. If transaction system integration is needed, replace 
`commit_row()` body only.
