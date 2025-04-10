from django.urls import path
from . import views

app_name = 'processing'

urlpatterns = [
    # Queue Management
    path('', views.ContractQueueListView.as_view(), name='contract_queue'),
    path('start/<int:queue_id>/', views.start_processing, name='start_processing'),
    path('download-template/', views.download_csv_template, name='download_csv_template'),
    path('download-test-data/', views.download_test_data, name='download_test_data'),
    path('upload/', views.upload_csv, name='upload_csv'),
    
    # Contract Processing
    path('contract/<int:pk>/', views.ProcessContractDetailView.as_view(), name='process_contract_detail'),
    path('contract/<int:pk>/edit/', views.ProcessContractUpdateView.as_view(), name='process_contract_edit'),
    path('contract/<int:pk>/finalize/', views.finalize_contract, name='finalize_contract'),
    
    # API Endpoints
    path('api/match-buyer/<int:pk>/', views.match_buyer, name='match_buyer'),
    path('api/match-nsn/<int:pk>/<int:clin_id>/', views.match_nsn, name='match_nsn'),
    path('api/match-supplier/<int:pk>/<int:clin_id>/', views.match_supplier, name='match_supplier'),
] 