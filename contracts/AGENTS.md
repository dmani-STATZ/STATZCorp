# AGENTS.md — `contracts` App

## 1. Purpose of This File

This file defines safe-edit guidance for AI coding agents and future developers working inside the `contracts` Django app. Read `contracts/CONTEXT.md` first for feature-level orientation. This file focuses on execution safety: what to read before editing, what breaks together, and where the real risk is.

---

## 2. App Scope

**Owns:**
- Canonical data for `Contract`, `Clin`, `Company`, `GovAction`, `FolderTracking`, `ContractSplit`, `Expedite`, `Note`, `Reminder`, `PaymentHistory`, `AcknowledgementLetter`, `ClinAcknowledgment`, `ClinShipment`, `IdiqContract`
- All lookup/code tables: `ContractStatus`, `Buyer`, `ContractType`, `ClinType`, `SalesClass`, `SpecialPaymentTerms`, `CanceledReason`
- The multi-tenant `Company` model and its branding/SharePoint configuration
- The full contract lifecycle UI: dashboard, contract management page, CLIN detail, folder tracking, finance audit, contract log, IDIQ pages
- All note, reminder, and payment history tracking for contracts and CLINs
- Acknowledgement letter generation and supplier management UI (delegates model reads to `suppliers` app)

**Does not own:**
- `Supplier`, `Contact`, `Certification`, `Classification` data — owned by `suppliers` app; `contracts` only reads and displays them
- `Nsn` (National Stock Number) — owned by `products` app; `Clin` holds an FK to it
- `SequenceNumber` — owned by `processing` app; used for PO/TAB number defaults
- `UserCompanyMembership` — owned by `users` app; `CompanyForm` syncs to it but does not define it
- The audit transaction trail — written by `transactions` app signals on `Contract`/`Clin` saves and on `ClinShipment` when `pod_date` changes. `Clin.ship_date` and `Clin.ship_qty` are tracked in `transactions/signals.py`; do not manually create `Transaction` rows when saving those fields — normal `Clin.save()` (including `save(update_fields=[...])` from views such as `complete_clin_shipping`) is enough for the audit trail.

**Role:** This is the core domain app of the project. Nearly every other app depends on or integrates with it.

---

## 3. Read This Before Editing

### Before changing models
- `contracts/models.py` — understand `on_delete` choices; `Company` uses `PROTECT` and `Nsn` uses `PROTECT`, meaning deletion will hard-fail if children exist
- `contracts/migrations/` — check the latest migration before adding fields; 37+ migrations exist with compound indexes
- `transactions` app signals — signals in `transactions/` fire on `Contract`, `Clin`, `ClinShipment` (tracked `pod_date`), and `Supplier` post/pre_save; renaming tracked fields will silently break the audit trail
- `processing/models.py` — `QueueContract` and `QueueClin` mirror Contract/Clin fields; a schema change may require parallel updates there
- `sales/` views/services that reference contract fields (e.g. SQL view DDL under `sales/sql/` joining `contracts_clin` / `contracts_contract` / `contracts_nsn`)

### Before changing views
- `contracts/views/mixins.py` — `ActiveCompanyQuerysetMixin` must remain on every queryset-based view; removing it leaks cross-tenant data
- `contracts/views/contract_views.py` — central hub; `ContractManagementView` builds a large context (CLINs, notes, splits, GovActions, folder tracking); adding keys here affects the main template
- `contracts/urls.py` — ~90 named URL patterns; reversals exist in templates throughout the project

### Before changing forms
- `contracts/forms.py` — `ClinForm.clean()` auto-calculates `item_value` and `quote_value`; disrupting this silently zeros out financial values
- `BaseFormMixin` — all forms inherit CSS widget styling from here; changes affect every form in the app
- `CompanyForm` — logo validation uses PIL (Pillow); PIL import is guarded, so if Pillow is missing it degrades silently

### Before changing templates
- Check for `{% include %}` partials: `notes_list.html`, `payment_history_popup.html`, `clin_shipments.html`, `contract_splits.html` are included in multiple parent templates
- **`clin_shipments.html` table layout:** In `mode="form"`, the data columns are Ship Date, Quantity, UOM, Comments, POD Date, then Actions (sixth column). Empty-state and footer `colspan` values must match that column count if the table changes. `ClinShipment.pod_date` is transaction-tracked; POD is edited via `openTransactionsEditModal` on CLIN detail (`window.clinShipmentContentTypeId`). The shipment audit (ⓘ) button is only rendered for server-rendered existing rows; rows injected by `ClinShipments.addNewShipment()` in `clin_shipments.js` intentionally omit it until the row exists in the database. The `#complete-shipping-row` footer action is only for form mode when fully shipped (`total_shipped == order_qty`); its visibility is toggled by `updateTotalShipQty()` in `clin_shipments.js` using `data-order-qty` on the `.section` wrapper (keep that attribute in sync if the partial changes).
- NSN and Supplier modals for the CLIN form are in `contracts/templates/contracts/modals/supplier_modal.html` and `nsn_modal.html`. The modal JS (`openSupplierModal`, `openNsnModal`, search/pagination helpers, and clear handlers) is defined in `clin_form.html`'s `extra_scripts` block. Element IDs `id_nsn`, `nsn_display`, `id_supplier`, and `supplier_display` are referenced by both the modal result wiring and the form — do not rename them without updating the script and modal templates together.
- JS files in `contracts/static/contracts/js/` are tightly bound to specific template IDs and form names; changing template element IDs or form field names breaks the JS
- **CSS architecture — no Tailwind:** This project does not use Tailwind in any form. Styling is Bootstrap 5 plus the project's own three-file CSS system. When editing templates:
  - New component or button styles → `static/css/app-core.css`
  - New utility/helper classes → `static/css/utilities.css`
  - New color tokens or dark mode overrides → `static/css/theme-vars.css`
  - **Do not touch:** `static/css/tailwind-compat.css`, `static/css/base.css`
  - If you encounter Tailwind utility classes in a template you are already editing, replace them with Bootstrap 5 equivalents or named classes from `app-core.css`. Do not leave Tailwind classes in place.
  - Inline `style` attributes are acceptable for one-off layout fixes but prefer a named class in `app-core.css` for anything reusable or that requires a hover/focus/pseudo-element state.

### Before changing exports/reports
- `contracts/utils/excel_utils.py` — wraps openpyxl with a lazy-import pattern to avoid NumPy conflicts; do not add direct `import openpyxl` elsewhere in the app
- `contracts/views/contract_log_views.py` — export logic reads CLIN fields by name; field renames here must be propagated
- `contracts/views/folder_tracking_views.py` — Excel export maps `FolderTracking` field names directly to column headers

### Before changing permissions/security logic
- `contracts/views/mixins.py` — `ActiveCompanyQuerysetMixin` raises `PermissionDenied` without active company
- `contracts/views/code_table_views.py`, `company_views.py`, `admin_tools.py` — all gated behind `user.is_superuser` checks; do not weaken to `is_staff`
- `contracts/context_processors.py` — reminder data is already scoped by `request.active_company`; adding unscoped queries here would leak data

---

## 4. Local Architecture / Change Patterns

**Multi-tenancy is pervasive.** Every model with user-visible data has a `company` FK. Querysets must be filtered by `request.active_company`. Use `ActiveCompanyQuerysetMixin` on CBVs; manually filter in function-based views.

**Views are fat orchestrators.** Business logic lives in views, not in dedicated service layers. `ContractManagementView` and `ContractCreateView` contain substantial logic. There is no `services.py`. New logic should follow this pattern unless you are refactoring intentionally.

**Forms own validation, but views own object creation.** `ClinForm` intentionally strips NSN/Supplier errors because the view handles those objects separately. Do not move that responsibility without updating both sides.

**AJAX/HTMX patterns are common.** Many views return HTML fragments (notes list, shipments, splits, payment history popup) for HTMX targets. These views often have both a "full page" and "partial" rendering path. Be careful not to break partial rendering when editing view context.

**Generic relations are used for Notes and PaymentHistory.** Both use `ContentType` + `object_id`. Do not add new relationships to `Note` or `PaymentHistory` by adding direct FKs — the generic relation is intentional. When querying, always pass `content_type` + `object_id` explicitly.

**`signals.py` is intentionally empty.** Signal handling for contracts was moved to `transactions/` and `users/`. Do not add new signals to `contracts/signals.py` without understanding the audit trail in `transactions/`.

**No background tasks.** There is no Celery integration. `ExportTiming` records timing data during request-time exports; it is not a background job.

---

## 5. Files That Commonly Need to Change Together

### Adding a field to `Contract`
- `contracts/models.py` + new migration
- `contracts/forms.py` (`ContractForm`, possibly `ContractCloseForm`/`ContractCancelForm`)
- `contracts/views/contract_views.py` (context for management page and create/update views)
- `contracts/templates/contracts/contract_form.html`, `contract_management.html`, `contract_detail.html`
- `contracts/views/contract_log_views.py` (if it should appear in exports)
- `processing/models.py` `QueueContract` (if the field is part of the import pipeline)
- `contracts/CONTRACTS_APP_CURRENT_STATE.md` (living doc)

### Adding a field to `Clin`
- `contracts/models.py` + new migration
- `contracts/forms.py` (`ClinForm`, especially `clean()`)
- `contracts/views/clin_views.py`, `api_views.py` (update-field API)
- `contracts/templates/contracts/clin_form.html` (create flow only) and `clin_detail.html` (read-only display with Transaction edit buttons on labels for tracked fields)
- `contracts/views/contract_log_views.py` (if exported)
- `processing/models.py` `QueueClin` (if imported)
- `transactions` app tracked-fields list (if auditable)

### Adding a new workflow action (e.g., contract toggle/status change)
- `contracts/views/contract_views.py` (handler function)
- `contracts/urls.py` (new URL pattern)
- `contracts/templates/contracts/contract_management.html` (UI trigger)

### Adding or renaming a code table (e.g., new `ContractType`)
- `contracts/models.py` (new model or field)
- `contracts/forms.py` (form widget update)
- `contracts/views/code_table_views.py` (register in admin page)
- `contracts/templates/contracts/code_table_admin.html`

### Changing folder tracking stacks
- `contracts/models.py` (`FolderTracking.stack` choices and `STACK_COLORS`)
- `contracts/views/folder_tracking_views.py` (color helpers, stack logic)
- `contracts/templates/contracts/folder_tracking.html` (color rendering)
- `contracts/utils/excel_utils.py` or folder tracking export helpers (column mapping)

### Changing supplier display in contracts
- `contracts/views/supplier_views.py`
- `suppliers/models.py` (source model — read-only from contracts)
- `contracts/templates/contracts/supplier_detail.html`, `supplier_list.html`
- `contracts/static/contracts/js/supplier_modal.js`

### Reminders popup window
- `contracts/views/reminder_views.py` — `reminders_popup`, `reminders_popup_add`, `reminders_popup_edit` views
- `contracts/templates/contracts/reminders_popup_base.html` — bare base template (no nav chrome)
- `contracts/templates/contracts/reminders_popup.html` — popup content template
- `contracts/urls.py` — `reminders_popup`, `reminders_popup_add`, `reminders_popup_edit` URL patterns
- `contracts/templates/contracts/contract_base.html` — `openRemindersPopup()` JS function and pop-out button in sidebar header

All popup views redirect back to `contracts:reminders_popup` on success, not to `contracts:reminders_list`.
The `toggle_reminder` and `delete_reminder` views use `HTTP_REFERER` for redirect — the popup URL will be the referer when those views are called from within the popup.
This pattern (popup_base + popup view + popup_add + popup_edit) is the approved pattern for future popup windows (e.g. Notes).

---

## 6. Cross-App Dependency Warnings

### This app depends on:
| App | What it uses |
|-----|-------------|
| `suppliers` | `Supplier`, `Contact`, `SupplierType`, `Certification`, `Classification`, `SupplierDocument` models |
| `products` | `Nsn` model (FK on `Clin`; `PROTECT` delete behavior) |
| `processing` | `SequenceNumber` for PO/TAB number defaults |
| `users` | `User`, `UserCompanyMembership`, `UserSettings`, `conditional_login_required` decorator, `request.active_company` middleware |

### Apps that depend on this app:
| App | How it depends |
|-----|---------------|
| `processing` | `QueueContract`/`QueueClin` map fields to `Contract`/`Clin`; matching engine creates live `Contract`/`Clin` rows |
| `transactions` | Registers pre/post_save signals on `Contract` and `Clin`; reads a list of tracked field names — **renaming any tracked field on these models silently drops audit history** |
| `sales` | Tier-1 supplier NSN scoring reads `contracts_*` via SQL Server view `dibbs_supplier_nsn_scored` (not Django `Clin` in `matching.py`) |
| `suppliers` | Some supplier URL patterns may reverse into contracts URLs |

### Specific high-risk field names (tracked by `transactions` signals):
Fields on `Contract` and `Clin` that appear to be tracked include: `contract_number`, `po_number`, `due_date`, `award_date`, `status`, and other core financial/date fields. Before renaming any of these, search `transactions/` for the field name to confirm it is not in a TRACKED_FIELDS list or hard-coded signal handler.

### Template / partial sharing:
- `notes_list.html` and `note_modal.html` are included in contract management, CLIN detail, and supplier detail templates. Changes to their expected context keys break all three locations.
- `payment_history_popup.html` is included from multiple views; its context variables (`payment_history`, `entity_type`, `entity_id`) must stay stable.

---

## 7. Security / Permissions Rules

- **Never remove `ActiveCompanyQuerysetMixin`** from a view that returns company-scoped data. Without it, users will see records from other companies.
- **`request.active_company` is set by middleware** (`users` app). Do not query `Company`-scoped models without it.
- Superuser-only views use `@user_passes_test(lambda u: u.is_superuser)`. Do not downgrade to `is_staff` — these views expose company config, logo upload, and bulk SharePoint updates.
- Note delete/edit requires `request.user == note.created_by or request.user.is_staff`. Do not generalize this to all authenticated users.
- Reminder completion toggle requires ownership check. Same pattern.
- Exports (contract log, folder tracking) are accessible to any logged-in user in the active company — treat them as sensitive; do not make them publicly accessible.
- Audit fields (`created_by`, `modified_by`) must be populated by views on create/update. Do not skip them — the contract log and admin both surface these.
- Some shipment API endpoints are CSRF-exempt (by design for HTMX). Do not mark additional endpoints CSRF-exempt without careful review.

---

## 8. Model and Schema Change Rules

- **Before renaming any `Contract` or `Clin` field:** search `transactions/` (signals, TRACKED_FIELDS), `processing/` (QueueContract/QueueClin field mapping), `sales/` (matching.py, views), and all `contracts/views/*.py` for string references to the field name.
- **`Nsn` FK on `Clin` uses `PROTECT`.** You cannot delete an `Nsn` that has CLINs. Any migration that changes this behavior will affect `products` app.
- **`Company` FK on most models uses `PROTECT`.** Deleting a `Company` will fail if any Contract, Clin, Note, Reminder, or GovAction exists for it. This is intentional.
- **Generic relations on `Note` and `PaymentHistory`** (`content_type` + `object_id`) are stable. Do not add direct FKs. If adding a new attachable model, follow the existing `ContentType` pattern.
- **Compound indexes exist** on `Contract` and `Clin` (e.g., `(status, due_date)`, `(contract, due_date)`). Check `models.py` Meta before adding overlapping indexes.
- **`AuditModel` base class** is used by ~8 models. Changes to `AuditModel` fields affect all of them simultaneously; write one migration for the base or confirm Django handles it correctly.
- **`ExportTiming`** stores JSON in `filters_applied`. If the filter shape changes in the log view, old `ExportTiming` rows may cause `json.loads` errors — handle gracefully.

---

## 9. View / URL / Template Change Rules

- **URL namespace is `contracts`.** There are ~90 named patterns. Before renaming any URL name, search the entire codebase for `contracts:<url_name>` (in templates with `{% url %}`) and `reverse('contracts:...')` in Python.
- **`ContractManagementView`** builds a large context dict from multiple queries (CLINs, notes, splits, GovActions, expedite, folder tracking). Adding a new context key is safe; removing or renaming an existing key requires checking `contract_management.html` and all its `{% include %}` partials.
- **`openShipmentsModal(clinId)`** on `contract_management.html` opens the read-only shipments modal and loads HTML from `GET /contracts/api/shipments/<clin_id>/?mode=detail`. If the CLIN card markup or the JavaScript that rebuilds the card (e.g. `fetchClinDetails`) is refactored, keep the **Shipments** button and its `onclick="openShipmentsModal(...)"` in sync with the server-rendered CLIN card (including `id="cd-shipments-btn"` on the initial SSR button when applicable).
- **HTMX partial views** (notes, shipments, splits, payment history) return HTML fragments. These views have an implicit contract with the frontend: the element IDs and `hx-target` selectors in templates must match. Changing response structure without updating `hx-target` references breaks the UI silently.
- **`contract_base.html`** (inferred from `contracts/templates/contracts/`) may serve as a base template for other templates in this app. Changing its block structure requires updating all child templates.
- **`clin_shipments.js`, `contract_splits.js`, `note_modal.js`, `supplier_modal.js`** reference DOM element IDs and form field `name` attributes. If you rename form fields or template element IDs, update these JS files.
- **Supplier detail templates** (`contracts/templates/contracts/supplier_*`) are rendered by `contracts/views/supplier_views.py` but read from `suppliers` models. Template changes here do not affect `suppliers` app templates.

---

## 10. Forms / Serializers / Input Validation Rules

- **`ClinForm.clean()`** silently removes NSN and Supplier validation errors — the view handles those objects separately via modal creation flows. Do not add hard validation on those fields inside the form.
- **`ClinForm.clean()`** auto-calculates `item_value = order_qty × unit_price` and `quote_value = order_qty × price_per_unit`. If you add new quantity/price fields, update this logic or the calculated values will be stale.
- **`ContractForm.clean_contract_number()`** enforces uniqueness excluding self (for updates). If you add a similar uniqueness check elsewhere, use the same `exclude pk` pattern.
- **`CompanyForm`** syncs `UserCompanyMembership` rows inside `save()`. If you override `save()` or call `form.save(commit=False)`, you must call `form.save_m2m()` or the membership sync will not run.
- **`BaseFormMixin`** auto-applies CSS classes via widget inspection. If a new widget type is introduced, add it to `BaseFormMixin` to keep styling consistent.
- **`ActiveUserModelChoiceField`** filters users to `is_active=True`. All user-selection dropdowns in this app must use this field, not bare `ModelChoiceField`.

---

## 11. Background Tasks / Signals / Automation Rules

- **No Celery tasks in this app.** All processing is synchronous.
- **`contracts/signals.py` is empty by design.** Signal handlers related to contracts live in `transactions/signals.py` (audit trail) and `users/signals.py`.
- **`transactions` app signals fire on every `Contract.save()` and `Clin.save()`.** This means: every view that saves a Contract or Clin triggers an audit row in `transactions`. If you bypass `.save()` (e.g., use `queryset.update()`), the audit trail will be skipped silently.
- **`context_processors.reminders_processor`** fires on every request. It queries reminders filtered by `request.active_company`. If this processor is slow, it affects every page load. Do not add heavy queries here.
- **`initialize_sequence_numbers`** management command seeds PO/TAB counters from existing contracts. Must be run after bulk data imports to avoid duplicate sequence numbers.
- **`ExportTiming`** records export duration during request-time. It degrades gracefully; it does not affect correctness if it fails.

---

## 12. Testing and Verification Expectations

**Current state:** `contracts/tests.py` is a stub. No automated tests exist for this app.

**After any model/migration change:**
- Run `python manage.py makemigrations --check` to confirm no missing migrations
- Open Django admin at `/admin/contracts/` and verify `Contract`, `Company`, and `Reminder` displays load without error
- Create a test contract in the UI and verify the management page loads

**After view changes:**
- Manually verify the contract management page (`/<pk>/`) loads for a real contract
- Verify the CLIN create form submits without errors and the CLIN detail page loads (Transactions modal for field edits)
- Open folder tracking view and verify the stack displays correctly
- If you changed an API view, test the HTMX interaction in the browser (notes add/delete, shipment add/edit, split operations)

**After form changes:**
- Submit the ContractForm with an empty required field and confirm validation fires
- Submit the ClinForm and confirm `item_value` is auto-calculated
- If you changed `CompanyForm`, upload a logo and verify validation catches invalid types

**After export changes:**
- Download a contract log export (CSV or XLSX) and open it — verify columns match expected headers
- Download a folder tracking export and check column alignment

**After permissions changes:**
- Log in as a non-superuser and confirm `/contracts/companies/` and `/contracts/code-tables/` return 403
- Log in as a user without an active company and confirm company-scoped views return `PermissionDenied`

**Cross-app smoke test after Contract/Clin schema changes:**
- Open the `processing` admin or queue view and verify QueueContract/QueueClin display without errors
- Check `transactions` audit log for recent records to confirm signals still fire

---

## 13. Known Footguns

1. **Renaming tracked fields without updating `transactions` signals.** The `transactions` app stores field names as strings. A rename will stop capturing that field in the audit trail with no error raised.

2. **Using `queryset.update()` instead of `.save()` on Contract/Clin.** This bypasses the `transactions` signals entirely. Always use `.save()` unless you intentionally want to skip the audit trail (rare; document it if so).

3. **Removing `ActiveCompanyQuerysetMixin` from a CBV.** Will serve all companies' data to any logged-in user. This is a multi-tenancy data leak.

4. **Changing `FolderTracking.stack` choice values.** These are stored as strings in the database. Changing a value in the choices list does not migrate existing rows. Existing rows will display as unknown/invalid choices.

5. **Changing `STACK_COLORS` in `FolderTracking`.** Stack colors are referenced in the Excel export by name. A rename breaks the export color mapping.

6. **Changing the `Note`/`PaymentHistory` context variable names** in view responses. These are consumed by `notes_list.html` and `payment_history_popup.html` partials, which are included in multiple parent templates. A rename breaks all of them.

7. **Calling `CompanyForm.save(commit=False)` without calling `form.save_m2m()`.** The `UserCompanyMembership` sync runs in `save()`. Skipping it leaves membership out of sync.

8. **Adding `import openpyxl` directly.** `contracts/utils/excel_utils.py` uses lazy-loading to avoid NumPy conflicts. Import openpyxl exclusively via this utility module.

9. **Breaking the `ClinForm.clean()` auto-calculation.** `item_value` and `quote_value` are not always entered by users; they are derived. If `clean()` fails, these fields silently remain zero and financial reporting is wrong.

10. **Changing URL pattern names without searching templates.** There are ~90 named URLs. `{% url 'contracts:...' %}` is used throughout `contracts/templates/contracts/` and possibly in `sales`, `processing`, and `suppliers` templates.

11. **The `AcknowledgementLetter` view references fields that do not exist on the model** (`recipient_name`, `recipient_address` per CONTEXT.md §17). This is a known stale view/template. Do not add logic that depends on these fields without first adding them to the model.

12. **`api_add_note` has debug `print` statements** and reads `request.content_type` (which is not set in AJAX requests). AJAX callers must pass `content_type_id` and `object_id` explicitly. This is a known bug.

13. **There is no longer a standalone CLIN edit page.** CLIN field edits are handled by the Transactions edit modal (`openTransactionsEditModal`). Do not re-add a dedicated CLIN edit view or `/contracts/clin/<pk>/edit/` route without removing the Transaction wiring from `clin_detail.html` first.

---

## 14. Safe Change Workflow

1. **Read `contracts/CONTEXT.md`** for feature context.
2. **Read the specific files** involved in your change (model, form, view, template, JS).
3. **Search repo-wide** for field names, URL names, and model imports before renaming anything.
   - `grep -r "contracts\." --include="*.py"` for model references
   - `grep -r "contracts:" --include="*.html"` for URL reversals
   - `grep -r "from contracts" --include="*.py"` for cross-app imports
4. **Check `transactions/`** if touching `Contract` or `Clin` fields.
5. **Check `processing/`** if touching fields that appear in the import/queue pipeline.
6. **Make minimal, scoped changes.** Avoid touching unrelated code in the same edit.
7. **Update all coupled files** (model + migration + form + template + admin + exports if relevant).
8. **Run migrations check:** `python manage.py makemigrations --check`
9. **Manually verify** the contract management page, CLIN form, and folder tracking load without errors.
10. **Verify cross-app:** open `processing` queue and `transactions` log to confirm they still function.

---

## 15. Quick Reference

### Primary files to inspect first
- `contracts/models.py` — all domain models
- `contracts/forms.py` — all forms and validation
- `contracts/urls.py` — all ~90 named URL patterns
- `contracts/views/contract_views.py` — core contract CRUD
- `contracts/views/mixins.py` — company-scoping enforcement

### Main coupled areas
- `Contract` ↔ `Clin` ↔ `ClinShipment` ↔ `PaymentHistory` (financial chain)
- `FolderTracking` ↔ `FolderStack` ↔ Excel export ↔ stack color constants
- `Note`/`Reminder` ↔ generic ContentType ↔ `notes_list.html` partial
- `ClinForm.clean()` ↔ `item_value`/`quote_value` auto-calculation
- `CompanyForm.save()` ↔ `UserCompanyMembership` sync

### Main cross-app dependencies
- `transactions` app: audit signals on `Contract`/`Clin` saves
- `processing` app: `QueueContract`/`QueueClin` mirror Contract/Clin schema
- `sales` app: tier-1 NSN scoring joins `contracts_*` in SQL Server view `dibbs_supplier_nsn_scored` (deployed via SSMS; see `sales/sql/dibbs_supplier_nsn_scored.sql`)
- `suppliers` app: `Supplier` model FKed from `Clin`
- `products` app: `Nsn` model FKed from `Clin` (PROTECT)
- `users` app: `request.active_company` middleware, `UserCompanyMembership`

### Main security-sensitive areas
- `ActiveCompanyQuerysetMixin` — multi-tenancy enforcement
- Superuser gates on `code_table_admin`, `company_views`, `admin_tools`
- Note/reminder owner checks
- Export endpoints (no public access)

### Riskiest edit types
- Renaming `Contract`/`Clin` fields (breaks `transactions` signals, `processing` queue, exports)
- Changing `FolderTracking.stack` choice values (stranded DB data)
- Weakening or removing `ActiveCompanyQuerysetMixin` (data leak)
- Using `queryset.update()` on `Contract`/`Clin` (skips audit trail)
- Changing `ClinForm.clean()` without understanding auto-calculated financial fields
