# imports/CONTEXT.md

## Current State
Full implementation complete. Services, views, templates, and AJAX endpoints 
are all in place. The app is functional end-to-end.

## What Was Built (this pass)
- `imports/services.py`:
  - parse_uploaded_file (CSV + Excel, in-memory, no disk write)
  - normalize_for_matching + token_sort (ACH- prefix strip, word-order normalization)
  - fuzzy_match_row (token-sort SequenceMatcher, threshold 0.72, caller treats <0.85 as low confidence)
  - resolve_fk_value / save_translation (ValueTranslationMap lookup + auto-save)
  - process_session (full matching pass, builds proposed_changes, sets session to 'previewing')
  - commit_row / commit_session (ONLY place target model is written during import)
- `imports/views.py`: dashboard, session_create (two-stage POST), session_detail, 
  session_commit, session_export_csv, ajax_search_target, ajax_update_match, 
  ajax_skip_row, ajax_save_translation
- `imports/urls.py`: all nine URL patterns
- Templates: `dashboard.html`, `session_create.html`, `session_detail.html`, 
  `partials/unresolved_fk_panel.html`
- `imports/templatetags/imports_tags.py` — `imports_get_item`, `import_target_label`, 
  `confidence_pct`, `unresolved_fk_panel` inclusion tag
- After a successful FK translation save, `ajax_save_translation` calls `process_session` 
  again and the UI reloads so proposed changes refresh

## What Is NOT Built Yet
- Per-row FK picker UI (only the global unresolved-FK panel)
- Transaction system integration in commit_row (V1 is direct ORM write)
- Automated test suite
