from django.urls import path, re_path
from django.views.generic import TemplateView
from users.views import test_app_name
from . import views
from .views.finance_views import (
    FinanceAuditView,
    PaymentHistoryView,
    payment_history_api
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
    
    # NSN and Supplier views
    NsnUpdateView,
    SupplierUpdateView,
    SupplierListView,
    SupplierSearchView,
    SupplierDetailView,
    SupplierCreateView,
    add_supplier_certification,
    delete_supplier_certification,
    get_supplier_certification,
    add_supplier_classification,
    delete_supplier_classification,
    get_supplier_classification,
    
    # Contact and Address views
    ContactListView,
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
    
    # Contract log views
    ContractLogView,
    export_contract_log,
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
)

from .views.contract_views import check_contract_number
from .views.api_views import get_select_options, update_clin_field
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
)

app_name = 'contracts'

urlpatterns = [
    # Dashboard views
    path('', ContractLifecycleDashboardView.as_view(), name='contracts_dashboard'),
    path('log/', ContractLogView.as_view(), name='contract_log_view'),
    path('log/export/', export_contract_log, name='export_contract_log'),
    path('log/get-export-estimate/', get_export_estimate, name='get_export_estimate'),
    path('open-export-folder/', open_export_folder, name='open_export_folder'),

    # Contract management
    path('create/', ContractCreateView.as_view(), name='contract_create'),
    path('<int:pk>/', ContractDetailView.as_view(), name='contract_detail'),
    path('<int:pk>/update/', ContractUpdateView.as_view(), name='contract_update'),
    path('<int:pk>/close/', ContractCloseView.as_view(), name='contract_close'),
    path('<int:pk>/cancel/', ContractCancelView.as_view(), name='contract_cancel'),
    path('<int:pk>/review/', ContractReviewView.as_view(), name='contract_review'),
    path('<int:pk>/mark-reviewed/', mark_contract_reviewed, name='mark_contract_reviewed'),
    
    # DD Form 1155 processing
    path('extract-dd1155/', extract_dd1155_data, name='extract_dd1155'),
    path('export-dd1155-text/', export_dd1155_text, name='export_dd1155_text'),
    path('export-dd1155-png/', export_dd1155_png, name='export_dd1155_png'),
    path('dd1155-test/', TemplateView.as_view(template_name='contracts/dd1155_test.html'), name='dd1155_test'),
    
    # CLIN management
    path('clin/new/', ClinCreateView.as_view(), name='clin_create'),
    path('contract/<int:contract_id>/clin/new/', ClinCreateView.as_view(), name='contract_clin_create'),
    path('clin/<int:pk>/', ClinDetailView.as_view(), name='clin_detail'),
    path('clin/<int:pk>/edit/', ClinUpdateView.as_view(), name='clin_update'),
    path('clin/acknowledgment/<int:pk>/edit/', ClinAcknowledgmentUpdateView.as_view(), name='clin_acknowledgment_update'),
    
    # NSN and Supplier management
    path('nsn/<int:pk>/edit/', NsnUpdateView.as_view(), name='nsn_edit'),
    path('suppliers/', SupplierListView.as_view(), name='supplier_list'),
    path('suppliers/search/', SupplierSearchView.as_view(), name='supplier_search'),
    path('supplier/<int:pk>/', SupplierDetailView.as_view(), name='supplier_detail'),
    path('supplier/<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_edit'),
    path('supplier/create/', SupplierCreateView.as_view(), name='supplier_create'),
    
    # Supplier Certifications and Classifications
    path('supplier/<int:supplier_id>/certification/add/', add_supplier_certification, name='supplier_add_certification'),
    path('supplier/<int:supplier_id>/certification/<int:pk>/delete/', delete_supplier_certification, name='supplier_delete_certification'),
    path('supplier/certification/<int:pk>/', get_supplier_certification, name='supplier_get_certification'),
    
    path('supplier/<int:supplier_id>/classification/add/', add_supplier_classification, name='supplier_add_classification'),
    path('supplier/<int:supplier_id>/classification/<int:pk>/delete/', delete_supplier_classification, name='supplier_delete_classification'),
    path('supplier/classification/<int:pk>/', get_supplier_classification, name='supplier_get_classification'),
    
    # Note management
    path('note/add/<int:content_type_id>/<int:object_id>/', add_note, name='add_note'),
    path('note/update/<int:pk>/', note_update, name='note_update'),
    path('note/delete/<int:note_id>/', delete_note, name='delete_note'),
    path('api/add-note/', api_add_note, name='api_add_note'),
    path('api/content-types/', list_content_types, name='list_content_types'),
    
    # Reminder management
    path('reminders/', ReminderListView.as_view(), name='reminders_list'),
    path('reminder/add/', add_reminder, name='add_reminder'),
    path('reminder/create/', add_reminder, name='create_reminder'),
    path('reminder/add/<int:note_id>/', add_reminder, name='add_note_reminder'),
    path('reminder/<int:reminder_id>/toggle/', toggle_reminder_completion, name='toggle_reminder'),
    path('reminder/<int:reminder_id>/delete/', delete_reminder, name='delete_reminder'),
    path('reminder/<int:reminder_id>/complete/', mark_reminder_complete, name='mark_reminder_complete'),
    path('reminder/<int:reminder_id>/edit/', edit_reminder, name='edit_reminder'),
    
    # Acknowledgement letter
    path('clin/<int:clin_id>/generate-letter/', generate_acknowledgement_letter, name='generate_acknowledgement_letter'),
    path('clin/<int:clin_id>/view-letter/', view_acknowledgement_letter, name='view_acknowledgement_letter'),
    path('letter/<int:pk>/edit/', AcknowledgementLetterUpdateView.as_view(), name='edit_acknowledgement_letter'),
    
    # API endpoints
    path('search/', contract_search, name='contract_search'),
    path('clin/<int:clin_id>/notes/', get_clin_notes, name='get_clin_notes'),
    path('clin/<int:clin_id>/toggle-acknowledgment/', toggle_clin_acknowledgment, name='toggle_clin_acknowledgment'),
    path('contract/<int:contract_id>/toggle-field/', toggle_contract_field, name='toggle_contract_field'),
    path('contract/<int:contract_id>/toggle-expedite/', toggle_expedite_status, name='toggle_expedite_status'),
    path('api/options/<str:field_name>/', get_select_options, name='get_select_options'),
    path('contract/<int:contract_id>/combined-notes/', get_combined_notes, name='get_combined_notes'),
    path('contract/<int:contract_id>/clin/<int:clin_id>/combined-notes/', get_combined_notes, name='get_combined_notes_with_clin'),
    
    # Test
    path('test-app-name/', test_app_name, name='test_app_name'),
    path('check-contract-number/', check_contract_number, name='check_contract_number'),
    
    # Contact management
    path('contacts/', ContactListView.as_view(), name='contact_list'),
    path('contacts/<int:pk>/', ContactDetailView.as_view(), name='contact_detail'),
    path('contacts/create/', ContactCreateView.as_view(), name='contact_create'),
    path('contacts/<int:pk>/update/', ContactUpdateView.as_view(), name='contact_update'),
    path('contacts/<int:pk>/delete/', ContactDeleteView.as_view(), name='contact_delete'),
    
    # Address management
    path('addresses/', AddressListView.as_view(), name='address_list'),
    path('addresses/create/', AddressCreateView.as_view(), name='address_create'),
    path('addresses/create/success/', AddressCreateSuccessView.as_view(), name='address_create_success'),
    path('addresses/<int:pk>/', AddressDetailView.as_view(), name='address_detail'),
    path('addresses/<int:pk>/update/', AddressUpdateView.as_view(), name='address_update'),
    path('addresses/<int:pk>/delete/', AddressDeleteView.as_view(), name='address_delete'),
    path('addresses/selector/', AddressSelectorView.as_view(), name='address_selector'),

    # Folder Tracking
    path('folder-tracking/', folder_tracking, name='folder_tracking'),
    path('folder-tracking/search/', search_contracts, name='search_contracts'),
    path('folder-tracking/add/', add_folder_tracking, name='add_folder_tracking'),
    path('folder-tracking/<int:pk>/close/', close_folder_tracking, name='close_folder_tracking'),
    path('folder-tracking/<int:pk>/toggle-highlight/', toggle_highlight, name='toggle_highlight'),
    path('folder-tracking/export/', export_folder_tracking, name='export_folder_tracking'),
    path('folder-tracking/<int:pk>/update-field/', update_folder_field, name='update_folder_field'),

    # IDIQ Contract URLs
    path('idiq/<int:pk>/', IdiqContractDetailView.as_view(), name='idiq_contract_detail'),
    path('idiq/<int:pk>/update/', IdiqContractUpdateView.as_view(), name='idiq_contract_update'),
    path('idiq/<int:pk>/details/create/', IdiqContractDetailsCreateView.as_view(), name='idiq_contract_detail_create'),
    path('idiq/<int:pk>/details/<int:detail_id>/delete/', IdiqContractDetailsDeleteView.as_view(), name='idiq_contract_detail_delete'),
    path('nsn/search/', NsnSearchView.as_view(), name='nsn_search'),
    path('supplier/search/', SupplierSearchView.as_view(), name='supplier_search'),

    # Finance Audit URLs
    path('finance-audit/', FinanceAuditView.as_view(), name='finance_audit'),
    path('finance-audit/<int:pk>/', FinanceAuditView.as_view(), name='finance_audit_detail'),
    
    # Payment History API
    path('api/payment-history/<int:clin_id>/<str:payment_type>/', 
         payment_history_api, 
         name='payment_history_api'),
         
    # CLIN Field Update API
    path('api/clin/<int:clin_id>/update-field/', 
         update_clin_field, 
         name='update_clin_field'),

    # Acknowledgment Letter URLs
    path('acknowledgment-letter/<int:clin_id>/', get_acknowledgment_letter, name='get_acknowledgment_letter'),
    path('acknowledgment-letter/<int:letter_id>/update/', update_acknowledgment_letter, name='update_acknowledgment_letter'),
] 