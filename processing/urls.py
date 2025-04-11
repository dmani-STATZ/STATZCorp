from django.urls import path
from .views.queue_views import (
    ContractQueueListView,
    get_next_numbers,
    download_csv_template,
    download_test_data,
    upload_csv,
    cancel_processing
)
from .views.processing_views import (
    ProcessContractDetailView,
    ProcessContractUpdateView,
    finalize_contract,
    get_process_contract,
    start_processing,
    match_buyer,
    match_nsn,
    match_supplier
)
from .views.api_views import (
    get_processing_contract,
    update_processing_contract,
    add_processing_clin,
    update_processing_clin,
    delete_processing_clin
)

app_name = 'processing'

urlpatterns = [
    # Queue Management
    path('queue/', ContractQueueListView.as_view(), name='queue'),
    path('queue/', ContractQueueListView.as_view(), name='contract_queue'),
    path('next-numbers/', get_next_numbers, name='get_next_numbers'),
    path('start-processing/<int:queue_id>/', start_processing, name='start_processing'),
    path('get-process-contract/<int:queue_id>/', get_process_contract, name='get_process_contract'),
    
    # Contract Processing
    path('contract/<int:pk>/', ProcessContractDetailView.as_view(), name='process_contract_detail'),
    path('contract/<int:pk>/edit/', ProcessContractUpdateView.as_view(), name='process_contract_edit'),
    path('contract/<int:process_contract_id>/finalize/', finalize_contract, name='finalize_contract'),
    
    # Matching Endpoints
    path('match-buyer/<int:process_contract_id>/', match_buyer, name='match_buyer'),
    path('match-nsn/<int:process_clin_id>/', match_nsn, name='match_nsn'),
    path('match-supplier/<int:process_clin_id>/', match_supplier, name='match_supplier'),
    
    # API Endpoints
    path('api/processing/<int:id>/', get_processing_contract, name='api_get_processing_contract'),
    path('api/processing/<int:id>/update/', update_processing_contract, name='api_update_processing_contract'),
    path('api/processing/<int:id>/clins/', add_processing_clin, name='api_add_processing_clin'),
    path('api/processing/<int:id>/clins/<int:clin_id>/', update_processing_clin, name='api_update_processing_clin'),
    path('api/processing/<int:id>/clins/<int:clin_id>/delete/', delete_processing_clin, name='api_delete_processing_clin'),
    
    # File Management
    path('download-template/', download_csv_template, name='download_csv_template'),
    path('download-test-data/', download_test_data, name='download_test_data'),
    path('upload/', upload_csv, name='upload_csv'),
    path('cancel-processing/<int:queue_id>/', cancel_processing, name='cancel_processing'),
] 