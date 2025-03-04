from django.urls import path
from . import views
from .views import (
    ContractDetailView,
    ClinDetailView,
    NsnUpdateView,
    SupplierUpdateView,
    contract_search,
    get_clin_notes,
    toggle_clin_acknowledgment,
    # New views
    ContractCreateView,
    ContractUpdateView,
    ContractCloseView,
    ContractCancelView,
    ClinCreateView,
    ClinUpdateView,
    ClinFinanceUpdateView,
    ClinAcknowledgmentUpdateView,
    ReminderListView,
    ContractLifecycleDashboardView,
    AcknowledgementLetterUpdateView,
    ContractLogView,
)
from users.views import test_app_name
from django.views.generic import TemplateView

app_name = 'contracts'

urlpatterns = [
    # Dashboard views
    path('', ContractLifecycleDashboardView.as_view(), name='contracts_dashboard'),
    path('log/', ContractLogView.as_view(), name='contract_log_view'),
    path('export-log/', views.export_contract_log, name='export_contract_log'),
    path('open-export-folder/', views.open_export_folder, name='open_export_folder'),

    # Contract management
    path('contract/new/', ContractCreateView.as_view(), name='contract_create'),
    path('contract/<int:pk>/', ContractDetailView.as_view(), name='contract_detail'),
    path('contract/<int:pk>/edit/', ContractUpdateView.as_view(), name='contract_update'),
    path('contract/<int:pk>/close/', ContractCloseView.as_view(), name='contract_close'),
    path('contract/<int:pk>/cancel/', ContractCancelView.as_view(), name='contract_cancel'),
    
    # DD Form 1155 processing
    path('extract-dd1155/', views.extract_dd1155_data, name='extract_dd1155'),
    path('dd1155-test/', TemplateView.as_view(template_name='contracts/dd1155_test.html'), name='dd1155_test'),
    
    # CLIN management
    path('clin/new/', ClinCreateView.as_view(), name='clin_create'),
    path('contract/<int:contract_id>/clin/new/', ClinCreateView.as_view(), name='contract_clin_create'),
    path('clin/<int:pk>/', ClinDetailView.as_view(), name='clin_detail'),
    path('clin/<int:pk>/edit/', ClinUpdateView.as_view(), name='clin_update'),
    path('clin/finance/<int:pk>/edit/', ClinFinanceUpdateView.as_view(), name='clin_finance_update'),
    path('clin/acknowledgment/<int:pk>/edit/', ClinAcknowledgmentUpdateView.as_view(), name='clin_acknowledgment_update'),
    
    # NSN and Supplier management
    path('nsn/<int:pk>/edit/', NsnUpdateView.as_view(), name='nsn_edit'),
    path('supplier/<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_edit'),
    
    # Note management
    path('note/add/<int:content_type_id>/<int:object_id>/', views.add_note, name='add_note'),
    path('note/delete/<int:note_id>/', views.delete_note, name='delete_note'),
    
    # Reminder management
    path('reminders/', ReminderListView.as_view(), name='reminders_list'),
    path('reminder/add/', views.add_reminder, name='add_reminder'),
    path('reminder/add/<int:note_id>/', views.add_reminder, name='add_note_reminder'),
    path('reminder/<int:reminder_id>/toggle/', views.toggle_reminder_completion, name='toggle_reminder'),
    path('reminder/<int:reminder_id>/delete/', views.delete_reminder, name='delete_reminder'),
    
    # Acknowledgement letter
    path('clin/<int:clin_id>/generate-letter/', views.generate_acknowledgement_letter, name='generate_acknowledgement_letter'),
    path('clin/<int:clin_id>/view-letter/', views.view_acknowledgement_letter, name='view_acknowledgement_letter'),
    path('letter/<int:pk>/edit/', AcknowledgementLetterUpdateView.as_view(), name='edit_acknowledgement_letter'),
    
    # API endpoints
    path('search/', contract_search, name='contract_search'),
    path('clin/<int:clin_id>/notes/', get_clin_notes, name='get_clin_notes'),
    path('clin/<int:clin_id>/toggle-acknowledgment/', toggle_clin_acknowledgment, name='toggle_clin_acknowledgment'),
    
    # Test
    path('test-app-name/', test_app_name, name='test_app_name'),
] 