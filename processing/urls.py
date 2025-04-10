from django.urls import path
from .views import (
    ContractQueueListView,
    get_next_numbers,
    start_processing,
    process_contract,
    download_csv_template,
    download_test_data,
    upload_csv
)

app_name = 'processing'

urlpatterns = [
    path('', ContractQueueListView.as_view(), name='contract_queue'),
    path('numbers/', get_next_numbers, name='get_numbers'),
    path('start/', start_processing, name='start_processing'),
    path('process/', process_contract, name='process_contract'),
    path('download/template/', download_csv_template, name='download_csv_template'),
    path('download/test/', download_test_data, name='download_test_data'),
    path('upload/', upload_csv, name='upload_csv'),
] 