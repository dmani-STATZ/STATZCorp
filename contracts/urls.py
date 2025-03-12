from django.urls import path
from django.views.generic import TemplateView
from users.views import test_app_name

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
    
    # Note views
    add_note,
    delete_note,
    note_update,
    api_add_note,
    list_content_types,
    
    # Reminder views
    ReminderListView,
    add_reminder,
    toggle_reminder_completion,
    delete_reminder,
    
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
    
    # DD1155 views
    extract_dd1155_data,
    export_dd1155_text,
    export_dd1155_png,
)

from .views.contract_views import check_contract_number
from .views.api_views import get_select_options

app_name = 'contracts'

urlpatterns = [
    # Dashboard views
    path('', ContractLifecycleDashboardView.as_view(), name='contracts_dashboard'),
    path('log/', ContractLogView.as_view(), name='contract_log_view'),
    path('export-log/', export_contract_log, name='export_contract_log'),
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
    path('supplier/<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_edit'),
    
    # Note management
    path('note/add/<int:content_type_id>/<int:object_id>/', add_note, name='add_note'),
    path('note/update/<int:note_id>/', note_update, name='note_update'),
    path('note/delete/<int:note_id>/', delete_note, name='delete_note'),
    path('api/add-note/', api_add_note, name='api_add_note'),
    path('api/content-types/', list_content_types, name='list_content_types'),
    
    # Reminder management
    path('reminders/', ReminderListView.as_view(), name='reminders_list'),
    path('reminder/add/', add_reminder, name='add_reminder'),
    path('reminder/add/<int:note_id>/', add_reminder, name='add_note_reminder'),
    path('reminder/<int:reminder_id>/toggle/', toggle_reminder_completion, name='toggle_reminder'),
    path('reminder/<int:reminder_id>/delete/', delete_reminder, name='delete_reminder'),
    
    # Acknowledgement letter
    path('clin/<int:clin_id>/generate-letter/', generate_acknowledgement_letter, name='generate_acknowledgement_letter'),
    path('clin/<int:clin_id>/view-letter/', view_acknowledgement_letter, name='view_acknowledgement_letter'),
    path('letter/<int:pk>/edit/', AcknowledgementLetterUpdateView.as_view(), name='edit_acknowledgement_letter'),
    
    # API endpoints
    path('search/', contract_search, name='contract_search'),
    path('clin/<int:clin_id>/notes/', get_clin_notes, name='get_clin_notes'),
    path('clin/<int:clin_id>/toggle-acknowledgment/', toggle_clin_acknowledgment, name='toggle_clin_acknowledgment'),
    path('api/options/<str:field_name>/', get_select_options, name='get_select_options'),
    
    # Test
    path('test-app-name/', test_app_name, name='test_app_name'),
    path('check-contract-number/', check_contract_number, name='check_contract_number'),
] 