from django.urls import path, re_path
from django.views.generic import TemplateView
from users.views import test_app_name
from . import views
from .views.finance_views import (
    FinanceAuditView,
    PaymentHistoryView,
    payment_history_api,
)

# Import views from the modular structure
from .views import (
    # Contract views
    ContractDetailView,
    ContractCreateView,
    ContractUpdateView,
    ContractCloseView,
    ContractCancelView,
    ContractReviewView,
    contract_search,
    mark_contract_reviewed,
    toggle_contract_field,
    toggle_expedite_status,
    # CLIN views
    ClinDetailView,
    ClinCreateView,
    ClinUpdateView,
    ClinAcknowledgmentUpdateView,
    get_clin_notes,
    toggle_clin_acknowledgment,
    clin_delete,
    # NSN and Supplier views
    NsnUpdateView,
    SupplierUpdateView,
    SupplierListView,
    SupplierSearchView,
    SupplierDetailView,
    SupplierCreateView,
    toggle_supplier_flag,
    update_supplier_header,
    update_supplier_address,
    update_supplier_notes,
    update_supplier_selects,
    update_supplier_compliance,
    update_supplier_files,
    save_supplier_contact,
    delete_supplier_contact,
    addresses_lookup,
    add_supplier_certification,
    update_supplier_certification,
    delete_supplier_certification,
    get_supplier_certification,
    add_supplier_classification,
    update_supplier_classification,
    delete_supplier_classification,
    get_supplier_classification,
    supplier_autocomplete,
    supplier_admin_tools,
    # Contact and Address views
    ContactListView,
    ContractManagementView,
    ContactDetailView,
    ContactCreateView,
    ContactUpdateView,
    ContactDeleteView,
    AddressListView,
    AddressDetailView,
    AddressCreateView,
    AddressUpdateView,
    AddressDeleteView,
    AddressCreateSuccessView,
    AddressSelectorView,
    # Note views
    add_note,
    delete_note,
    note_update,
    api_add_note,
    list_content_types,
    get_combined_notes,
    # Reminder views
    ReminderListView,
    add_reminder,
    toggle_reminder_completion,
    delete_reminder,
    mark_reminder_complete,
    edit_reminder,
    # Acknowledgement letter views
    generate_acknowledgement_letter,
    view_acknowledgement_letter,
    AcknowledgementLetterUpdateView,
    # Dashboard views
    ContractLifecycleDashboardView,
    DashboardMetricDetailView,
    dashboard_metric_detail_export,
    # Contract log views
    ContractLogView,
    export_contract_log,
    export_contract_log_xlsx,
    open_export_folder,
    get_export_estimate,
    # DD1155 views
    extract_dd1155_data,
    export_dd1155_text,
    export_dd1155_png,
    # Folder Tracking views
    folder_tracking,
    add_folder_tracking,
    close_folder_tracking,
    toggle_highlight,
    export_folder_tracking,
    search_contracts,
    update_folder_field,
    # Split views
    create_split,
    update_split,
    delete_split,
    get_contract_splits,
    # Shipment views
    create_shipment,
    update_shipment,
    delete_shipment,
    get_clin_shipments,
    # Code table views
    code_table_admin,
)

from .views.contract_views import check_contract_number
from .views.api_views import (
    get_select_options,
    update_clin_field,
    create_buyer,
    create_supplier,
    contract_day_counts,
)
from .views.idiq_views import (
    IdiqContractDetailView,
    IdiqContractUpdateView,
    IdiqContractDetailsCreateView,
    IdiqContractDetailsDeleteView,
    NsnSearchView,
    SupplierSearchView,
)

from .views.acknowledgment_views import (
    get_acknowledgment_letter,
    update_acknowledgment_letter,
    generate_acknowledgment_letter_doc,
)

from .views import payment_history_views
from .views.folder_tracking_views import (
    folderstack_list,
    folderstack_save,
    folderstack_move,
    folderstack_delete,
)
from .views.company_views import (
    CompanyListView,
    CompanyCreateView,
    CompanyUpdateView,
    CompanyDeleteView,
)

app_name = "contracts"

urlpatterns = [
    # CLIN Shipment URLs - Moving these to the top
    path("api/shipments/create/", create_shipment, name="create_shipment"),
    path(
        "api/shipments/update/<int:shipment_id>/",
        update_shipment,
        name="update_shipment",
    ),
    path(
        "api/shipments/delete/<int:shipment_id>/",
        delete_shipment,
        name="delete_shipment",
    ),
    path("api/shipments/<int:clin_id>/", get_clin_shipments, name="get_clin_shipments"),
    # Dashboard views
    path("", ContractLifecycleDashboardView.as_view(), name="contracts_dashboard"),
    path(
        "dashboard/metric-detail/",
        DashboardMetricDetailView.as_view(),
        name="dashboard_metric_detail",
    ),
    path(
        "dashboard/metric-detail/export/",
        dashboard_metric_detail_export,
        name="dashboard_metric_detail_export",
    ),
    path("log/", ContractLogView.as_view(), name="contract_log_view"),
    path("log/export/", export_contract_log, name="export_contract_log"),
    path("log/export-xlsx/", export_contract_log_xlsx, name="export_contract_log_xlsx"),
    path("log/get-export-estimate/", get_export_estimate, name="get_export_estimate"),
    path("open-export-folder/", open_export_folder, name="open_export_folder"),
    # Contract management
    path("create/", ContractCreateView.as_view(), name="contract_create"),
    path("<int:pk>/", ContractManagementView.as_view(), name="contract_management"),
    path("<int:pk>/detail/", ContractDetailView.as_view(), name="contract_detail"),
    path("<int:pk>/update/", ContractUpdateView.as_view(), name="contract_update"),
    path("<int:pk>/close/", ContractCloseView.as_view(), name="contract_close"),
    path("<int:pk>/cancel/", ContractCancelView.as_view(), name="contract_cancel"),
    path("<int:pk>/review/", ContractReviewView.as_view(), name="contract_review"),
    path(
        "<int:pk>/mark-reviewed/", mark_contract_reviewed, name="mark_contract_reviewed"
    ),
    # DD Form 1155 processing
    path("extract-dd1155/", extract_dd1155_data, name="extract_dd1155"),
    path("export-dd1155-text/", export_dd1155_text, name="export_dd1155_text"),
    path("export-dd1155-png/", export_dd1155_png, name="export_dd1155_png"),
    path(
        "dd1155-test/",
        TemplateView.as_view(template_name="contracts/dd1155_test.html"),
        name="dd1155_test",
    ),
    # CLIN management
    path("clin/new/", ClinCreateView.as_view(), name="clin_create"),
    path(
        "contract/<int:contract_id>/clin/new/",
        ClinCreateView.as_view(),
        name="contract_clin_create",
    ),
    path("clin/<int:pk>/", ClinDetailView.as_view(), name="clin_detail"),
    path("clin/<int:pk>/edit/", ClinUpdateView.as_view(), name="clin_update"),
    path("clin/<int:pk>/delete/", clin_delete, name="clin_delete"),
    path(
        "clin/acknowledgment/<int:pk>/edit/",
        ClinAcknowledgmentUpdateView.as_view(),
        name="clin_acknowledgment_update",
    ),
    # NSN and Supplier management
    path("nsn/<int:pk>/edit/", NsnUpdateView.as_view(), name="nsn_edit"),
    path("suppliers/", SupplierListView.as_view(), name="supplier_list"),
    path(
        "suppliers/autocomplete/", supplier_autocomplete, name="supplier_autocomplete"
    ),
    path("suppliers/search/", SupplierSearchView.as_view(), name="supplier_search"),
    path("supplier/<int:pk>/", SupplierDetailView.as_view(), name="supplier_detail"),
    path("supplier/<int:pk>/edit/", SupplierUpdateView.as_view(), name="supplier_edit"),
    path("supplier/create/", SupplierCreateView.as_view(), name="supplier_create"),
    path(
        "supplier/<int:pk>/toggle-flag/",
        toggle_supplier_flag,
        name="supplier_toggle_flag",
    ),
    path(
        "supplier/<int:pk>/quick-update/",
        update_supplier_header,
        name="supplier_quick_update",
    ),
    path(
        "supplier/<int:pk>/update-notes/",
        update_supplier_notes,
        name="supplier_update_notes",
    ),
    path(
        "supplier/<int:pk>/update-selects/",
        update_supplier_selects,
        name="supplier_update_selects",
    ),
    path(
        "supplier/<int:pk>/update-compliance/",
        update_supplier_compliance,
        name="supplier_update_compliance",
    ),
    path(
        "supplier/<int:pk>/update-files/",
        update_supplier_files,
        name="supplier_update_files",
    ),
    path(
        "supplier/<int:pk>/address/",
        update_supplier_address,
        name="supplier_update_address",
    ),
    path(
        "supplier/<int:pk>/contact/save/",
        save_supplier_contact,
        name="supplier_save_contact",
    ),
    path(
        "supplier/<int:pk>/contact/<int:contact_id>/delete/",
        delete_supplier_contact,
        name="supplier_delete_contact",
    ),
    path("addresses/lookup/", addresses_lookup, name="addresses_lookup"),
    # Supplier Certifications and Classifications
    path(
        "supplier/<int:supplier_id>/certification/add/",
        add_supplier_certification,
        name="supplier_add_certification",
    ),
    path(
        "supplier/<int:supplier_id>/certification/<int:pk>/update/",
        update_supplier_certification,
        name="supplier_update_certification",
    ),
    path(
        "supplier/<int:supplier_id>/certification/<int:pk>/delete/",
        delete_supplier_certification,
        name="supplier_delete_certification",
    ),
    path(
        "supplier/certification/<int:pk>/",
        get_supplier_certification,
        name="supplier_get_certification",
    ),
    path(
        "supplier/<int:supplier_id>/classification/add/",
        add_supplier_classification,
        name="supplier_add_classification",
    ),
    path(
        "supplier/<int:supplier_id>/classification/<int:pk>/update/",
        update_supplier_classification,
        name="supplier_update_classification",
    ),
    path(
        "supplier/<int:supplier_id>/classification/<int:pk>/delete/",
        delete_supplier_classification,
        name="supplier_delete_classification",
    ),
    path(
        "supplier/classification/<int:pk>/",
        get_supplier_classification,
        name="supplier_get_classification",
    ),
    # Note management
    path("note/add/<int:content_type_id>/<int:object_id>/", add_note, name="add_note"),
    path("note/update/<int:pk>/", note_update, name="note_update"),
    path("note/delete/<int:note_id>/", delete_note, name="delete_note"),
    path("api/add-note/", api_add_note, name="api_add_note"),
    path("api/content-types/", list_content_types, name="list_content_types"),
    # Reminder management
    path("reminders/", ReminderListView.as_view(), name="reminders_list"),
    path("reminder/add/", add_reminder, name="add_reminder"),
    path("reminder/create/", add_reminder, name="create_reminder"),
    path("reminder/add/<int:note_id>/", add_reminder, name="add_note_reminder"),
    path(
        "reminder/<int:reminder_id>/toggle/",
        toggle_reminder_completion,
        name="toggle_reminder",
    ),
    path("reminder/<int:reminder_id>/delete/", delete_reminder, name="delete_reminder"),
    path(
        "reminder/<int:reminder_id>/complete/",
        mark_reminder_complete,
        name="mark_reminder_complete",
    ),
    path("reminder/<int:reminder_id>/edit/", edit_reminder, name="edit_reminder"),
    # Acknowledgement letter
    path(
        "clin/<int:clin_id>/generate-letter/",
        generate_acknowledgement_letter,
        name="generate_acknowledgement_letter",
    ),
    path(
        "clin/<int:clin_id>/view-letter/",
        view_acknowledgement_letter,
        name="view_acknowledgement_letter",
    ),
    path(
        "letter/<int:pk>/edit/",
        AcknowledgementLetterUpdateView.as_view(),
        name="edit_acknowledgement_letter",
    ),
    # API endpoints
    path("search/", contract_search, name="contract_search"),
    path("clin/<int:clin_id>/notes/", get_clin_notes, name="get_clin_notes"),
    path(
        "clin/<int:clin_id>/toggle-acknowledgment/",
        toggle_clin_acknowledgment,
        name="toggle_clin_acknowledgment",
    ),
    path(
        "contract/<int:contract_id>/toggle-field/",
        toggle_contract_field,
        name="toggle_contract_field",
    ),
    path(
        "contract/<int:contract_id>/toggle-expedite/",
        toggle_expedite_status,
        name="toggle_expedite_status",
    ),
    path(
        "api/options/<str:field_name>/", get_select_options, name="get_select_options"
    ),
    path(
        "contract/<int:contract_id>/combined-notes/",
        get_combined_notes,
        name="get_combined_notes",
    ),
    path(
        "contract/<int:contract_id>/clin/<int:clin_id>/combined-notes/",
        get_combined_notes,
        name="get_combined_notes_with_clin",
    ),
    path("api/buyers/create/", create_buyer, name="api_buyer_create"),
    path("api/suppliers/create/", create_supplier, name="api_supplier_create"),
    path("api/nsn/create/", views.api_views.create_nsn, name="api_nsn_create"),
    path("api/day-counts/", contract_day_counts, name="contract_day_counts"),
    # Test
    path("test-app-name/", test_app_name, name="test_app_name"),
    path("check-contract-number/", check_contract_number, name="check_contract_number"),
    # Contact management
    path("contacts/", ContactListView.as_view(), name="contact_list"),
    path("contacts/<int:pk>/", ContactDetailView.as_view(), name="contact_detail"),
    path("contacts/create/", ContactCreateView.as_view(), name="contact_create"),
    path(
        "contacts/<int:pk>/update/", ContactUpdateView.as_view(), name="contact_update"
    ),
    path(
        "contacts/<int:pk>/delete/", ContactDeleteView.as_view(), name="contact_delete"
    ),
    # Address management
    path("addresses/", AddressListView.as_view(), name="address_list"),
    path("addresses/create/", AddressCreateView.as_view(), name="address_create"),
    path(
        "addresses/create/success/",
        AddressCreateSuccessView.as_view(),
        name="address_create_success",
    ),
    path("addresses/<int:pk>/", AddressDetailView.as_view(), name="address_detail"),
    path(
        "addresses/<int:pk>/update/", AddressUpdateView.as_view(), name="address_update"
    ),
    path(
        "addresses/<int:pk>/delete/", AddressDeleteView.as_view(), name="address_delete"
    ),
    path("addresses/selector/", AddressSelectorView.as_view(), name="address_selector"),
    # Folder Tracking
    path("folder-tracking/", folder_tracking, name="folder_tracking"),
    path("folder-tracking/search/", search_contracts, name="search_contracts"),
    path("folder-tracking/add/", add_folder_tracking, name="add_folder_tracking"),
    path(
        "folder-tracking/<int:pk>/close/",
        close_folder_tracking,
        name="close_folder_tracking",
    ),
    path(
        "folder-tracking/<int:pk>/toggle-highlight/",
        toggle_highlight,
        name="toggle_highlight",
    ),
    path(
        "folder-tracking/export/", export_folder_tracking, name="export_folder_tracking"
    ),
    path(
        "folder-tracking/<int:pk>/update-field/",
        update_folder_field,
        name="update_folder_field",
    ),
    # IDIQ Contract URLs
    path(
        "idiq/<int:pk>/", IdiqContractDetailView.as_view(), name="idiq_contract_detail"
    ),
    path(
        "idiq/<int:pk>/update/",
        IdiqContractUpdateView.as_view(),
        name="idiq_contract_update",
    ),
    path(
        "idiq/<int:pk>/details/create/",
        IdiqContractDetailsCreateView.as_view(),
        name="idiq_contract_detail_create",
    ),
    path(
        "idiq/<int:pk>/details/<int:detail_id>/delete/",
        IdiqContractDetailsDeleteView.as_view(),
        name="idiq_contract_detail_delete",
    ),
    path("nsn/search/", NsnSearchView.as_view(), name="nsn_search"),
    path("supplier/search/", SupplierSearchView.as_view(), name="supplier_search"),
    # Finance Audit URLs
    path("finance-audit/", FinanceAuditView.as_view(), name="finance_audit"),
    path(
        "finance-audit/<int:pk>/",
        FinanceAuditView.as_view(),
        name="finance_audit_detail",
    ),
    # Payment History API
    path(
        "api/payment-history/<str:entity_type>/<int:entity_id>/details/",
        payment_history_views.get_entity_details,
        name="payment_history_entity_details",
    ),
    path(
        "api/payment-history/<str:entity_type>/<int:entity_id>/<str:payment_type>/",
        payment_history_views.payment_history_api,
        name="payment_history_api",
    ),
    # CLIN Field Update API
    path(
        "api/clin/<int:clin_id>/update-field/",
        update_clin_field,
        name="update_clin_field",
    ),
    # Acknowledgment Letter URLs
    path(
        "acknowledgment-letter/<int:clin_id>/",
        get_acknowledgment_letter,
        name="get_acknowledgment_letter",
    ),
    path(
        "acknowledgment-letter/<int:letter_id>/update/",
        update_acknowledgment_letter,
        name="update_acknowledgment_letter",
    ),
    path(
        "acknowledgment-letter/<int:letter_id>/generate/",
        generate_acknowledgment_letter_doc,
        name="generate_acknowledgment_letter_doc",
    ),
    # Split URLs
    path("api/splits/create/", create_split, name="create_split"),
    path("api/splits/update/<int:split_id>/", update_split, name="update_split"),
    path("api/splits/delete/<int:split_id>/", delete_split, name="delete_split"),
    path(
        "api/splits/<int:contract_id>/", get_contract_splits, name="get_contract_splits"
    ),
    # FolderStack AJAX endpoints
    path("folder-stack/list/", folderstack_list, name="folderstack_list"),
    path("folder-stack/save/", folderstack_save, name="folderstack_save"),
    path("folder-stack/<int:pk>/move/", folderstack_move, name="folderstack_move"),
    path(
        "folder-stack/<int:pk>/delete/", folderstack_delete, name="folderstack_delete"
    ),
    # Company management (superuser-only)
    path("companies/", CompanyListView.as_view(), name="company_list"),
    path("companies/create/", CompanyCreateView.as_view(), name="company_create"),
    path("companies/<int:pk>/edit/", CompanyUpdateView.as_view(), name="company_edit"),
    path(
        "companies/<int:pk>/delete/", CompanyDeleteView.as_view(), name="company_delete"
    ),
    # Code table management (superuser-only)
    path("code-tables/", code_table_admin, name="code_table_admin"),
    # Admin tools
    path("admin-tools/", supplier_admin_tools, name="admin_tools"),
]
