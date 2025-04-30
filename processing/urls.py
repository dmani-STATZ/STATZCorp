from django.urls import path
from django.shortcuts import redirect

from .views.processing_views import (
    ProcessContractDetailView,
    ProcessContractUpdateView,
    finalize_contract,
    get_process_contract,
    start_processing,
    match_buyer,
    match_nsn,
    match_supplier,
    match_idiq,
    cancel_process_contract,
    save_and_return_to_queue,
    create_split_view,
    update_split_view,
    delete_split_view,
    cancel_processing,
    mark_ready_for_review,
    start_new_contract,
    finalize_and_email_contract,
    save_contract_data,
    ContractQueueListView,
    get_next_numbers,
    download_csv_template,
    download_test_data,
    upload_csv,
    initiate_processing,
    delete_queue_contract
)
from .views.api_views import (
    get_processing_contract,
    update_processing_contract,
    add_processing_clin,
    update_processing_clin,
    delete_processing_clin,
    update_process_contract_field,
    update_clin_field
)

app_name = 'processing'

urlpatterns = [
    # Queue Management
    path('queue/', ContractQueueListView.as_view(), name='queue'),
    path('queue/delete/<int:queue_id>/', delete_queue_contract, name='delete_queue_contract'),
    path('start-new-contract/', start_new_contract, name='start_new_contract'),
    path('next-numbers/', get_next_numbers, name='get_next_numbers'),
    path('queue/cancel/<int:queue_id>/', cancel_process_contract, name='queue_cancel_processing'),
    
    # Contract Processing
    path('process/<int:process_contract_id>/', lambda request, process_contract_id: redirect('processing:process_contract_edit', pk=process_contract_id), name='process_contract'),
    path('contract/<int:pk>/', ProcessContractDetailView.as_view(), name='process_contract_detail'),
    path('contract/<int:pk>/edit/', ProcessContractUpdateView.as_view(), name='process_contract_edit'),
    path('contract/<int:process_contract_id>/save/', save_and_return_to_queue, name='save_and_return'),
    path('save-contract-data/<int:process_contract_id>/', save_contract_data, name='save_contract_data'),
    path('contract/<int:process_contract_id>/finalize/', finalize_contract, name='finalize_contract'),
    path('contract/<int:process_contract_id>/finalize-and-email/', finalize_and_email_contract, name='finalize_and_email_contract'),
    path('process-contract/cancel/<int:process_contract_id>/', cancel_process_contract, name='cancel_process_contract'),
    path('start-processing/<int:queue_id>/', start_processing, name='start_processing'),
    path('get-process-contract/<int:queue_id>/', get_process_contract, name='get_process_contract'),
    
    # Matching Endpoints
    path('match-buyer/<int:process_contract_id>/', match_buyer, name='match_buyer'),
    path('match-nsn/<int:process_clin_id>/', match_nsn, name='match_nsn'),
    path('match-supplier/<int:process_clin_id>/', match_supplier, name='match_supplier'),
    path('match-idiq/<int:process_contract_id>/', match_idiq, name='match_idiq'),
    
    # API Endpoints
    path('api/processing/<int:id>/', get_processing_contract, name='api_get_processing_contract'),
    path('api/processing/<int:id>/update/', update_processing_contract, name='api_update_processing_contract'),
    path('api/contract/<int:id>/clin/create/', add_processing_clin, name='api_add_processing_clin'),
    path('api/processing/<int:id>/clins/<int:clin_id>/', update_processing_clin, name='api_update_processing_clin'),
    path('api/processing/<int:id>/clins/<int:clin_id>/delete/', delete_processing_clin, name='api_delete_processing_clin'),
    path('api/update-field/<int:pk>/', update_process_contract_field, name='update_process_contract_field'),
    path('api/update-clin-field/<int:pk>/clin/<int:clin_id>/', update_clin_field, name='update_clin_field'),
    
    # File Management
    path('download-template/', download_csv_template, name='download_csv_template'),
    path('download-test-data/', download_test_data, name='download_test_data'),
    path('upload/', upload_csv, name='upload_csv'),

    path('contract/split/create/', create_split_view, name='create_split'),
    path('contract/split/<int:split_id>/update/', update_split_view, name='update_split'),
    path('contract/split/<int:split_id>/delete/', delete_split_view, name='delete_split'),

    path('process-contract/<int:process_contract_id>/cancel/', cancel_process_contract, name='cancel_processing'),
    path('process-contract/<int:process_contract_id>/mark-ready/', mark_ready_for_review, name='mark_ready_for_review'),

] 