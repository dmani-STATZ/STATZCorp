# Contracts Context

## 1. Purpose
A multi-company contract-workspace that owns the full lifecycle from contract header to CLINs, suppliers, financials, notes, reminders, dashboards, export-ready logs, and upload-ready SharePoint links. The current-state document (`contracts/CONTRACTS_APP_CURRENT_STATE.md`) outlines how Contracts stores header data, CLINs, suppliers, notes/reminders, GovAction tracking, payment history, folder-tracking stacks, and cross-tenant dashboards, so this app is the authoritative place for contract operations within the project.

## 2. App Identity
- **Django app name:** `contracts` (AppConfig `contracts.apps.ContractsConfig`, verbose name 'Contracts Management').
- **Filesystem path:** `contracts/` inside the repo root.
- **Role:** Core feature app; it exposes the main user portal for contract entry/review, plus admin tooling (companies, code tables, folder stacks) and supporting data (suppliers, buyers, IDIQ contracts) for the rest of the ecosystem.
- **Contextual hooks:** Most views expect `request.active_company` (see `contracts/views/mixins.py`), and the app decorates views with `STATZWeb.decorators.conditional_login_required` or `@login_required` to enforce authentication.

## 3. High-Level Responsibilities
- Host the canonical `Contract`/`Clin`/`Company` data model, including contract status flows, SharePoint document links, and contract splits (`contracts/models.py`).
- Drive the operational UI: dashboards, contract management page, CLIN detail, contract log, folder tracking, finance audit, supplier search, and acknowledgements (`contracts/views/*.py` and `contracts/templates/contracts/`).
- Manage transactional data (notes, reminders, payment history, shipments, GovActions, acknowledgements) through forms, partials, and API endpoints so users can add contextual data without leaving the contract workspace (`contracts/forms.py`, `contracts/views/note_views.py`, `contracts/views/reminder_views.py`, `contracts/views/payment_history_views.py`).
- Provide admin/superuser conveniences: code table CRUD (`contracts/views/code_table_views.py`), company CRUD plus branding controls (`contracts/views/company_views.py`), and supplier admin bulk imports (`contracts/views/admin_tools.py`).
- Expose structured APIs for UI widgets and integrators (`contracts/views/api_views.py`, `contracts/urls.py`), including select-option APIs, payment-history, IDIQ helpers, splits/shipments, and contract-day counts.

## 4. Key Files and What They Do
- `contracts/models.py`: defines the audit-friendly objects (`Contract`, `Clin`, `Note`, `Reminder`, `PaymentHistory`, `FolderTracking`, etc.), generic relation patterns, SharePoint link builder (`Contract.get_sharepoint_documents_url`), and business helpers (e.g., `ContractSplit.create_split`, `FolderTracking.close_record`).
- `contracts/forms.py`: styling mixin plus all ModelForms (Contract, CLIN, Supplier, Note, Reminder, AcknowledgementLetter, IDIQ, code tables) with custom cleaning logic (e.g., `ContractForm.clean_contract_number`, `ClinForm.clean` adjustments for NSN/supplier validation, `CompanyForm` membership sync and color validation).
- `contracts/urls.py`: wiring for dashboards, contract/CLIN CRUD, supplier screens, notes/reminders, folder tracking, finance/audit, API endpoints, IDIQ pages, superuser code tables, and admin tools.
- `contracts/views/contract_views.py`: the heart of contract CRUD, review toggles, expedite handling, contract search modal, and SharePoint/document UI for the management page; also runs CLIN/notes context for the main workspace.
- `contracts/views/clin_views.py` (+ `shipment_views.py`, `payment_history_views.py`, `acknowledgement_letter_views.py`): CLIN create/detail (field edits use the Transactions modal on `clin_detail.html`), shipment APIs, payment-history popup logic, and acknowledgement-letter generation/edit flows. The former standalone CLIN edit view and `/contracts/clin/<pk>/edit/` route were removed.
- `contracts/views/dashboard_views.py`: dashboard metrics, metric-detail exports, and period utilities that feed `contracts/templates/contracts/contract_lifecycle_dashboard.html`.
- `contracts/views/folder_tracking_views.py`: folder-stack UI, pagination toggle, Excel export helpers (`contracts/utils/excel_utils.py`), stack colors, search, add/close/highlight actions.
- `contracts/views/supplier_views.py`: supplier list/detail/edit (reusing `suppliers.models`), inline updates (headers, addresses, notes, compliance), and supplier search/views tied into contract data for quick navigation.
- `contracts/views/contract_log_views.py`: paginated CLIN list used for exports, annotated with split totals and acknowledgement helper text.
- `contracts/views/api_views.py`: JSON APIs powering dropdowns, CLIN quick updates, NSN/buyer/supplier creation, contract day counts, and select-option pagination that feed the front-end modals and HTMX widgets.
- `contracts/context_processors.py`: reminder sidebar data scoped by `request.active_company` plus user-setting driven “upcoming days” window before rendering global templates.
- `contracts/utils/contracts_schema.py`: schema generator (used for documentation/query tooling) that enumerates tables, fields, and foreign keys.
- `contracts/utils/*`: helper modules for Excel exports (`excel_utils.py`) and lazy image/PDF tooling (`image_processing.py`).
- `contracts/management/commands/initialize_sequence_numbers.py`: seeds the shared PO/TAB sequence numbers from existing contracts; `refresh_nsn_view.py` now only reports the legacy `nsn_view` database view.
- `contracts/CONTRACTS_APP_CURRENT_STATE.md` & `Contracts Application.md`: living documentation summarizing current features (dashboard, notes split, reminders, GovActions) that future changes should keep in sync.
- `contracts/templates/contracts/`: main user-facing templates (`contract_management.html`, `clin_form.html`, `clin_detail.html`, `contract_lifecycle_dashboard.html`, `folder_tracking.html`, `contract_log_view.html`) plus reusable partials/includes (`notes_list.html`, `note_modal.html`, `clin_shipments.html`, `contract_splits.html`, `payment_history_popup.html`). The CLIN create form (`clin_form.html`, create-only) loads NSN and Supplier picker modals from `contracts/templates/contracts/modals/nsn_modal.html` and `supplier_modal.html` (included templates), not inline modal markup. CLIN detail (`clin_detail.html`) wires tracked fields to the Transactions edit modal and change-history panel.
- `contracts/static/contracts/js/`: JS glue for contract splits, CLIN shipments, note modal interactions, and the supplier modal (`supplier_modal.js`).

## 5. Data Model / Domain Objects
- **Company (contracts/models.py):** stores tenant info plus branding/SharePoint URLs; enforces unique slug, supply defaults (`Company.get_default_company`), and has optional logo/colors used by templates.
- **AuditModel base class:** adds `created_by/modified_by` FKs (Django `User`) plus timestamp helpers used by `Contract`, `Clin`, `Reminder`, `Note`, etc.
- **Contract:** header-level data (`contract_number`, `po_number`, `status`, `buyer`, `contract_type`, `scheduled dates`, `contract_value`, `plan_gross`, `special_payment_terms`, `company`). Has generic `Note` and `PaymentHistory` relations, `ContractSplit` children, and helper properties (`total_split_value`, `get_sharepoint_documents_url`).
- **Clin:** belongs to a `Contract`, tracks supplier/NSN (`suppliers.models.Supplier`, `products.models.Nsn`), payment fields, due/ship dates, `special_payment_terms`, `GenericRelations` to notes/payment history, plus log fields and `ClinShipment` children.
- **PaymentHistory & Note:** generic relations to `Contract`, `Clin`, and `IdiqContract` with audit fields; `PaymentHistory.clean` enforces payment-type validity per entity.
- **ClinShipment & ContractSplit:** support multi-shipment tracking and split accounting; `ContractSplit` exposes classmethods to create/update/delete splits.
- **IdiqContract & IdiqContractDetails:** capture umbrella IDIQ info plus allowed NSN/supplier combinations.
- **Supplier, Buyer, ContractType, ClinType, SalesClass, SpecialPaymentTerms, CanceledReason, GovAction, FolderStack/FolderTracking, Reminder, AcknowledgementLetter, ClinAcknowledgment, Address:** all defined in `contracts/models.py` with FK ties back to `contracts.Contract` or suppliers and featured in forms/views for code tables, GovAction tabs, reminders sidebar, and folder-tracking UI.

## 6. Request / User Flow
- **Dashboard entry (`/contracts/`):** `ContractLifecycleDashboardView` shows metric cards, overdue/open counts, and a recent-contract list; metric detail exports live at `/contracts/dashboard/metric-detail/` (`contracts/views/dashboard_views.py`).
- **Contract lifecycle:** `/contracts/create/`, `<pk>/update/`, `<pk>/close/`, `<pk>/cancel/`, `<pk>/review/`, toggles (`mark-reviewed`, `toggle-contract-field`, `toggle-expedite-status`). Management page renders header, CLIN tabs, GovActions, notes, and expedite controls (`contracts/views/contract_views.py`).
- **CLIN flows:** `/contracts/clin/new/` (or `/contracts/contract/<id>/clin/new/`), `<pk>/`, `<pk>/delete/`, `<pk>/acknowledgment/edit/`, plus APIs for updating fields, shipments, and payment history (`clin_views.py`, `shipment_views.py`, `payment_history_views.py`). CLIN field edits on the detail page use the Transactions app edit modal (`openTransactionsEditModal`).
- **Supplier management:** list/search/detail/create/edit routes under `/contracts/supplier/...` and AJAX-ish updates for headers, addresses, notes, compliance, contacts, certifications/classifications (`contracts/views/supplier_views.py`). Supplier detail paginates related contracts/CLINs.
- **Notes & reminders:** Add/edit/delete URLs (`note/add/`, `note/update/`, `note/delete/`) plus AJAX `api/add-note/` that optionally seeds reminders; reminders list/add/toggle/complete at `/contracts/reminders/` and include sidebar context from `context_processors.reminders_processor`.
- **Folder tracking:** `/contracts/folder-tracking/` with add/close/export, stack management endpoints, and search powered by `folder_tracking_views.py` plus `FolderStack`/`FolderTracking` models.
- **Contract log:** `/contracts/log/` shows CLIN-centric grid with filters and exports (`contracts/views/contract_log_views.py`).
- **Finance audit & payment:** `/contracts/finance-audit/` renders `finance_audit.html`; `api/payment-history/<entity_type>/<entity_id>/<payment_type>/` handles payment-entry persistence (updates totals on CLIN records).
- **IDIQ data:** `/contracts/idiq/<pk>/`, update, IDIQ detail creation/deletion, and search endpoints for NSN/suppliers (`contracts/views/idiq_views.py`).
- **Superuser admin:** `/contracts/companies/`, `/contracts/code-tables/`, `/contracts/admin-tools/` for bulk supplier SharePoint URLs.
- **Supporting APIs:** `/contracts/search/`, `/contracts/clin/<id>/notes/`, `/contracts/clin/<id>/details/`, `/contracts/supplier/<id>/info/`, `/contracts/api/options/<field>/`, `/contracts/api/clin/<id>/update-field/`, `/contracts/api/splits/*`, `/contracts/api/shipments/*`, `/contracts/api/nsn/create`, `/contracts/api/buyers/create`, `/contracts/api/suppliers/create`, `/contracts/api/day-counts/`, `/contracts/api/payment-history/*`.

## 7. Templates and UI Surface Area
- Server-rendered templates under `contracts/templates/contracts/`: `contract_management.html` (primary hub), `contract_detail.html`, `contract_form.html`, `clin_detail.html`, `clin_form.html`, `contract_lifecycle_dashboard.html`, `contract_log_view.html`, `folder_tracking.html`, `finance_audit.html`, and modals such as `admin_tools.html`.
- Shared partials for reusable UI: `contract_menu_items.html`, `cancel_contract_modal.html`, `folderstack_modal.html`, `checkbox_field.html`, `payment_history_popup.html`, `notes_list.html`, `note_modal.html`, `clin_shipments.html`, `contract_splits.html`, `acknowledgment_letter_form.html`.
- Static assets: JS under `contracts/static/contracts/js/` (CLIN shipments, contract splits, note modal interactions) plus `contracts/static/js/supplier_modal.js`; CSS/JS align with Bootstrap-style classes applied in `BaseFormMixin`.
- Templates rely on HTMX-like endpoints (note modal, payment history) and modals for splits/shipments; dashboards offer CSV exports, charts, and contract search modals.

## 8. Admin / Staff Functionality
- `contracts/admin.py` registers `Contract`, `Company`, and `Reminder` with `ActiveUserAdminMixin` so foreign keys (assigned/reviewed/reminder users) are filtered to active `User` records.
- Superuser views wired into `contracts/urls.py` allow CRUD on `Company` (branding/SharePoint fields), `code_table_admin`, and `supplier_admin_tools` (CSV/XLSX SharePoint URL ingestion).
- Staff also access the contract log export/estimate endpoints, finance audit detail, folder tracking stacks, and the GovActions tab on the contract management page.

## 9. Forms, Validation, and Input Handling
- `BaseFormMixin` enforces consistent widget styling; `ActiveUserModelChoiceField` narrows user dropdowns to active accounts.
- Contract forms: `ContractForm` (with `clean_contract_number`, date/time widgets, and `SequenceNumber` defaults) plus `ContractCloseForm`/`ContractCancelForm` for specialized actions.
- CLIN form: `ClinForm` (initializes supplier/NSN querysets only when needed, auto-calculates `item_value`/`quote_value`, removes supplier/NSN errors since the view handles them, and uses date/number widgets); `ClinAcknowledgmentForm` and `AcknowledgementLetterForm` capture GOV/PO workflows.
- Supporting forms: `CompanyForm` (color validation, membership sync with `users.models.UserCompanyMembership`, `sharepoint_*` fields), `SupplierForm`, `NoteForm`, `ReminderForm`, `ContractSearchForm` (HTMX attributes), `FolderTrackingForm`, IDIQ/Buyer/SpecialPaymentTerm forms, and code-table forms.
- Custom validation patterns include `CompanyForm.clean_primary_color/clean_secondary_color`, `ContractForm.clean_contract_number`, `Reminder`/`Note` forms linking to generic content types, and JSON-based APIs ensuring required fields for payment history/NSN creation.

## 10. Business Logic and Services
- Contract helpers: `Contract.get_sharepoint_documents_url` builds SharePoint folder links; `ContractSplit` classmethods manage splits; `ExportTiming.get_estimated_time` feeds export progress estimates.
- Dashboard metrics aggregate contract counts/due totals for each period (`dashboard_views.get_period_boundaries`, `get_dashboard_metric_queryset`).
- Folder Tracking uses `FolderStack`/`FolderTracking` plus color helpers (`color_to_argb`, `get_contrast_color`) and `contracts/utils/excel_utils` for exports.
- Payment flows: `payment_history_api` recalculates CLIN totals when entries are added; `PaymentHistory.clean` ensures payment types match the entity.
- Supplier admin tooling (`admin_tools.py`) uses fuzzy matching and SharePoint heuristics to bulk-update `Supplier.files_url`.
- Sequence numbers: `processing.models.SequenceNumber` supplies PO/TAB defaults, and `initialize_sequence_numbers` ensures counters start above existing maxima.
- Reminders context processor aggregates the next 0–7 days of reminders via `users.user_settings.UserSettings` and gracefully degrades when migrations lag.

## 11. Integrations and Cross-App Dependencies
- `products.models.Nsn` is referenced by `Clin`, `IdiqContractDetails`, the CLIN form, and NSN search endpoints.
- `suppliers.models.*` (Supplier, Contact, SupplierType, Certification/Classification, SupplierDocument) are the source of supplier CRUD, certification/classification edits, and supplier detail dashboards.
- `processing.models.SequenceNumber` provides PO/TAB defaults and is advanced when contracts are created (`contracts/views/contract_views.py`).
- `users` assets: `UserCompanyMembership` powers `CompanyForm`, `UserSettings` drives reminder sidebar preferences, and `STATZWeb.decorators.conditional_login_required` plus `request.active_company` tie the app to the shared authentication layer.
- `STATZWeb` and `sales` indirectly depend on contract data (e.g., docs mention `award_date` used in the DIBBS spec), so any schema change ripple affects those reports/integrations.

## 12. URL Surface / API Surface
- Dashboard & exports: `/contracts/`, `/contracts/dashboard/metric-detail/`, `/contracts/dashboard/metric-detail/export/`.
- Contract CRUD: `/contracts/create/`, `<pk>/`, `<pk>/detail/`, `<pk>/update/`, `/contracts/close/`, `/contracts/cancel/`, `/contracts/review/`, toggles like `mark-reviewed`, `toggle-contract-field`, `toggle-expedite-status`.
- CLIN flows: `/contracts/clin/new/`, `/contracts/contract/<id>/clin/new/`, `<pk>/`, `<pk>/delete/`, `<pk>/acknowledgment/edit/`, plus supporting APIs for `get_clin_notes`, `get_clin_details`, `toggle_clin_acknowledgment`, `save_clin_log_fields`, and shipping/payment/split endpoints.
- Supplier & NSN: `/contracts/suppliers/`, `/contracts/supplier/<pk>/`, `/contracts/supplier/create/`, autocomplete/search endpoints, update-notes/compliance/address, certification/classification CRUD, `/contracts/addresses/*` and `/contracts/supplier_admin_tools/`.
- Notes/reminders: `note/add/<ct>/<id>/`, `note/update/<pk>/`, `note/delete/<id>/`, `/contracts/api/add-note/`, `/contracts/api/content-types/`, `/contracts/reminders/`, `/contracts/reminder/<id>/toggle/complete/delete/edit`.
- Folder tracking/log: `/contracts/folder-tracking/` plus search/add/close/toggle/export, `/contracts/log/`, `/contracts/open-export-folder/`, `/contracts/log/export/`.
- IDIQ & code tables: `/contracts/idiq/<pk>/`, update/detail creation/deletion, `/contracts/code-tables/`, `/contracts/companies/`, `/contracts/admin-tools/`.
- APIs: `/contracts/api/options/<field>/`, `/contracts/api/clin/<id>/update-field/`, `/contracts/api/nsn/create`, `/contracts/api/buyers/create`, `/contracts/api/suppliers/create`, `/contracts/api/day-counts/`, `/contracts/api/payment-history/<entity_type>/<entity_id>/<payment_type>/`, `/contracts/api/splits/*`, `/contracts/api/shipments/*`.

## 13. Permissions / Security Considerations
- Views are decorated with `conditional_login_required` or `@login_required`; `ActiveCompanyQuerysetMixin` enforces company scoping and raises `PermissionDenied` without an active company (`contracts/views/mixins.py`).
- Notes require creator or staff to delete/edit (`contracts/views/note_views.py`); reminders ensure only the owner (or staff) can toggle completion (`contracts/views/reminder_views.py`).
- Superuser-only endpoints include `code_table_admin`, `company CRUD`, and `supplier_admin_tools` (`user_passes_test` wrappers + `user.is_superuser`).
- Some AJAX APIs are CSRF-exempt (shipments), but most JSON endpoints enforce POST/GET restrictions and login.
- Audit fields (`created_by`, `modified_by`) exist on the majority of models, so business logic must populate them (e.g., `ClinCreateView`).

## 14. Background Processing / Scheduled Work
- Management commands: `initialize_sequence_numbers` (re-syncs PO/TAB numbers), and `refresh_nsn_view` (now deprecated, only reports stats for the legacy view).
- No Celery tasks; background-like behavior includes `FolderTracking` exports and `ExportTiming` (which records timing so the UI can estimate export duration).
- Reminders are generated/read during requests via `context_processors.reminders_processor` (no periodic jobs).

## 15. Testing Coverage
- `contracts/tests.py` remains the default `TestCase` stub; no automated tests currently cover this app.
- Regression safety presently depends on manual verification of contract/CLIN workflows, so new features should add smoke/integration tests.

## 16. Migrations / Schema Notes
- 37 migrations exist (`contracts/migrations/0001_initial.py` through `0037_company_sharepoint_urls.py`), documenting the addition of payment history, folder stacks, supplier docs, GovActions, sharepoint URLs, etc.
- Many migrations adjust indexes (`0011_contract_plan_gross`, `0015_contract_contract_prime_idx`), restructure CLIN/Contract fields (`0030_contact_supplier_alter_supplier_contact`, `0034_contract_supplier_alter_clin_nsn_alter_clin_supplier_and_more`), simplify payment history (`0017_paymenthistory.py`), and add folder-tracking metadata (`0021_folderstack.py`, `0022_foldertracking_stack_id.py`).

## 17. Known Gaps / Ambiguities
- `contracts/views/payment_history_views.py`’s `PaymentHistoryView.get` still returns a stubbed `history` list while the real data comes from `payment_history_api`.
- `contracts/views/acknowledgement_letter_views.py` references fields such as `recipient_name`/`recipient_address` that are missing from the `AcknowledgementLetter` model, so the view/template pair is likely stale.
- `contracts/views/note_views.api_add_note` retains debug `print` statements and references `request.content_type` (not set), so AJAX requests must pass `content_type_id`/`object_id` explicitly.
- No automated tests exist, so assumptions about GovAction/log, reminders, or payment history have not been regression-tested.
- Supplier admin CSV/XLSX import uses fuzzy matching, so renaming suppliers can break bulk updates if matching fails.

## 18. Safe Modification Guidance for Future Developers / AI Agents
- Respect `request.active_company`. When querying models with a `company` FK, either filter manually or use `ActiveCompanyQuerysetMixin`; otherwise you risk leaking cross-tenant data.
- Changing contract/CLIN fields requires updates across `contracts/forms.py`, the relevant templates/partials, `contracts/views/contract_views.py`, search APIs, and `contracts/CONTRACTS_APP_CURRENT_STATE.md` so the documented workflow stays accurate.
- Renaming generic-related fields (`Note`, `PaymentHistory`) needs updates to the partials (`notes_list.html`), AJAX payloads (note modal/`api/add-note/`), and any exports that rely on `content_type_id`.
- Folder-tracking logic is tightly coupled with color constants (`FolderTracking.STACK_COLORS`, `folder_tracking.html`, and the Excel export helpers); change carefully when editing stack names or colors.
- Supplier/contact changes touch both `contracts/views/supplier_views.py` and the `suppliers` app models/forms; re-run or update `supplier_admin_tools` if file URLs or naming conventions change.
- Keep `contracts/CONTRACTS_APP_CURRENT_STATE.md` (and `Contracts Application.md`) in sync with code changes to preserve the documented expectations for this app’s UX.

## 19. Quick Reference
- **Primary models:** `Contract`, `Clin`, `Company`, `PaymentHistory`, `ClinShipment`, `ContractSplit`, `FolderTracking`, `FolderStack`, `Note`, `Reminder`, `GovAction`, `AcknowledgementLetter` (`contracts/models.py`).
- **Main URLs:** dashboard `/contracts/`, contract management `<pk>/`, CLIN CRUD `/contracts/clin/*`, folder tracking `/contracts/folder-tracking/`, contract log `/contracts/log/`, finance audit `/contracts/finance-audit/`, supplier management `/contracts/suppliers/`, and APIs under `/contracts/api/*` (`contracts/urls.py`).
- **Key templates:** `contracts/templates/contracts/contract_management.html`, `contract_lifecycle_dashboard.html`, `folder_tracking.html`, `contract_log_view.html`, `clin_detail.html`, `clin_form.html` (create-only), `contract_form.html`, plus partials `notes_list.html`, `payment_history_popup.html`, `clin_shipments.html`, `contract_splits.html`.
- **Key dependencies:** `products.models.Nsn`, `suppliers.models.Supplier` (and related contacts/certifications), `processing.models.SequenceNumber`, `users.user_settings.UserSettings`, `STATZWeb.decorators.conditional_login_required`, and `openpyxl`/`webcolors` for exports.
- **Risky files to review first:** `contracts/models.py`, `contracts/views/contract_views.py`, `contracts/forms.py`, `contracts/views/api_views.py`, `contracts/views/folder_tracking_views.py` (Excel export + pagination logic).
