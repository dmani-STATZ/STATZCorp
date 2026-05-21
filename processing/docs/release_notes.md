# Processing app release notes

## Split Row Persistence & Unsaved Indicator

"Add Split" now immediately saves the new row to the database when the
analyst enters a company name and tabs/clicks away. No longer requires
a separate "Save CLIN" click to persist a brand-new split row.
All split rows that have unsaved edits now display a yellow "Unsaved"
badge in the Actions column. The badge clears automatically when
"Save CLIN" completes successfully.
Fallback behavior preserved: if the immediate persist fails (network
error etc.), the row remains in DOM-only mode and Save CLIN will still
catch it via the existing persist_clin_splits_for_contract path.
